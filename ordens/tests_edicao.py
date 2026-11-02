from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from ativos.models import ComponenteInstalado, IntervencaoComponente
from estoque.models import Componente, MovimentoEstoque
from estoque.selectors import componentes_com_saldo
from estoque.services import registrar_entrada
from .edicao import editar_servico, itens_do_servico
from .models import RegistroAtendimento, RevisaoServico
from .selectors import registros_para_apresentacao, filtrar_ordens, ordens_para_consulta
from .services import abrir_os, concluir_os, encerrar_os, registrar_servico
from .tests import preparar, novo_ativo


class EdicaoServicoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario, cls.categoria, cls.departamento, cls.componentes = preparar()
        cls.ativo = novo_ativo(cls.usuario, cls.categoria, cls.departamento, cls.componentes)
        cls.ordem = abrir_os(ativo_id=cls.ativo.pk, entregue_por="Pessoa A", problema="RAM defeituosa", usuario=cls.usuario, chave_confirmacao=uuid.uuid4())[0]
        registrar_entrada(componente_id=cls.componentes["ram"].pk, quantidade=4, origem="compra", data=timezone.localdate(), usuario=cls.usuario, chave_confirmacao=uuid.uuid4())
        cls.registro = registrar_servico(ordem_id=cls.ordem.pk, descricao="Memória nova instalada.", itens=[cls.item()],
            usuario=cls.usuario, chave_confirmacao=uuid.uuid4(), versao=1)[0]

    @classmethod
    def item(cls, acao="instalar", quantidade=1, tipo="ram"):
        return {"componente_id": cls.componentes[tipo].pk, "acao": acao, "quantidade": quantidade}

    def dados(self, **alteracoes):
        self.ordem.refresh_from_db()
        return {"ordem_id": self.ordem.pk, "registro_id": self.registro.pk, "descricao": "Memória nova instalada e defeituosa retirada.",
                "justificativa": "A retirada não foi informada no lançamento inicial.", "itens": [self.item(), self.item("retirar_sem_retorno")],
                "usuario": self.usuario, "chave_confirmacao": uuid.uuid4(), "versao": self.ordem.versao, **alteracoes}

    def confirmar(self, **alteracoes):
        dados = self.dados(**alteracoes)
        previa, _ = editar_servico(**dados)
        return editar_servico(**dados, previa=previa)[0]

    def saldo(self):
        return componentes_com_saldo().get(pk=self.componentes["ram"].pk).saldo

    def quantidade(self):
        return self.ativo.componentes_instalados.get(componente=self.componentes["ram"]).quantidade

    def test_esquecimento_de_retirada_corrige_sem_reconsumir_e_sem_outro_servico(self):
        self.assertEqual(self.quantidade(), 2)
        self.assertEqual(self.saldo(), 3)
        revisao = self.confirmar()
        self.assertEqual(self.quantidade(), 1)
        self.assertEqual(self.saldo(), 3)
        self.assertEqual(RegistroAtendimento.objects.filter(tipo="servico").count(), 1)
        self.registro.refresh_from_db()
        self.assertEqual(self.registro.descricao, "Memória nova instalada.")
        atual = registros_para_apresentacao(self.ordem)[0]
        self.assertEqual(atual.descricao_exibicao, revisao.descricao)
        self.assertEqual(len(atual.pecas_exibicao), 2)

    def test_previa_nao_grava_nem_altera_estoque(self):
        previa, criado = editar_servico(**self.dados())
        self.assertFalse(criado)
        self.assertEqual(previa["efeitos"], [])
        self.assertEqual(self.quantidade(), 2)
        self.assertEqual(self.saldo(), 3)
        self.assertFalse(RevisaoServico.objects.exists())

    def test_corrigir_quantidade_compensa_apenas_a_diferenca(self):
        self.confirmar(itens=[self.item(quantidade=2)])
        self.assertEqual(self.quantidade(), 3)
        self.assertEqual(self.saldo(), 2)
        self.confirmar(itens=[self.item(quantidade=1)], descricao="Apenas uma memória foi instalada.")
        self.assertEqual(self.quantidade(), 2)
        self.assertEqual(self.saldo(), 3)
        self.assertEqual(RevisaoServico.objects.count(), 2)
        self.assertEqual(MovimentoEstoque.objects.filter(origem="correcao").count(), 2)

    def test_alterar_retornar_peca_para_estoque_ajusta_saldo_sem_mudar_composicao(self):
        self.confirmar()
        self.confirmar(itens=[self.item(), self.item("retirar_reutilizar")], descricao="Peça retirada testada e útil.")
        self.assertEqual(self.quantidade(), 1)
        self.assertEqual(self.saldo(), 4)
        self.confirmar(itens=[self.item(), self.item("retirar_sem_retorno")], descricao="A peça retirada era defeituosa.")
        self.assertEqual(self.quantidade(), 1)
        self.assertEqual(self.saldo(), 3)

    def test_excluir_item_de_instalacao_compensa_consumo_e_configuracao(self):
        self.confirmar(itens=[], descricao="Somente diagnóstico, sem peça utilizada.")
        self.assertEqual(self.quantidade(), 1)
        self.assertEqual(self.saldo(), 4)

    def test_descricao_pode_ser_corrigida_apos_outro_servico_sem_mudar_pecas(self):
        registrar_servico(ordem_id=self.ordem.pk, descricao="Retirada posterior", itens=[self.item("retirar_sem_retorno")],
            usuario=self.usuario, chave_confirmacao=uuid.uuid4(), versao=2)
        self.confirmar(itens=[self.item()], descricao="Texto corrigido do primeiro serviço.")
        self.assertEqual(self.quantidade(), 1)
        self.assertEqual(self.saldo(), 3)

    def test_intervencao_posterior_impede_desfazer_pecas_antigas(self):
        registrar_servico(ordem_id=self.ordem.pk, descricao="Retirada posterior", itens=[self.item("retirar_sem_retorno")],
            usuario=self.usuario, chave_confirmacao=uuid.uuid4(), versao=2)
        with self.assertRaisesMessage(ValidationError, "alterações posteriores"):
            editar_servico(**self.dados())
        self.assertEqual(self.quantidade(), 1)
        self.assertFalse(RevisaoServico.objects.exists())

    def test_peca_distinta_alterada_depois_nao_bloqueia_correcao_de_ram(self):
        registrar_servico(ordem_id=self.ordem.pk, descricao="Retirada da fonte", itens=[self.item("retirar_sem_retorno", tipo="fonte")],
            usuario=self.usuario, chave_confirmacao=uuid.uuid4(), versao=2)
        self.confirmar()
        self.assertEqual(self.quantidade(), 1)

    def test_saldo_insuficiente_e_retirada_excessiva_nao_gravam(self):
        for itens in ([self.item(quantidade=6)], [self.item(), self.item("retirar_sem_retorno", quantidade=3)]):
            with self.subTest(itens=itens), self.assertRaises(ValidationError):
                editar_servico(**self.dados(itens=itens))
        self.assertEqual(self.saldo(), 3)
        self.assertEqual(self.quantidade(), 2)
        self.assertFalse(RevisaoServico.objects.exists())

    def test_instalacao_nova_nao_autoriza_retirar_pecas_que_nao_existiam_no_servico(self):
        with self.assertRaisesMessage(ValidationError, "antes deste serviço"):
            editar_servico(**self.dados(itens=[self.item(quantidade=2), self.item("retirar_reutilizar", quantidade=2)]))
        self.assertEqual(self.quantidade(), 2)
        self.assertEqual(self.saldo(), 3)

    def test_reenvio_retorna_mesma_revisao_e_rejeita_payload_alterado(self):
        dados = self.dados(itens=[self.item(quantidade=2)])
        previa, _ = editar_servico(**dados)
        um, _ = editar_servico(**dados, previa=previa)
        dois, criado = editar_servico(**dados, previa=previa)
        self.assertFalse(criado)
        self.assertEqual(um.pk, dois.pk)
        self.assertEqual(self.saldo(), 2)
        with self.assertRaisesMessage(ValidationError, "outros dados"):
            editar_servico(**{**dados, "descricao":"Outro texto"}, previa=previa)

    def test_previa_antiga_por_mudanca_de_saldo_exige_nova_conferencia(self):
        dados = self.dados(itens=[self.item(quantidade=2)])
        previa, _ = editar_servico(**dados)
        registrar_entrada(componente_id=self.componentes["ram"].pk, quantidade=1, origem="compra", data=timezone.localdate(), usuario=self.usuario, chave_confirmacao=uuid.uuid4())
        with self.assertRaisesMessage(ValidationError, "saldos mudaram"):
            editar_servico(**dados, previa=previa)

    def test_versao_antiga_conclusao_e_encerramento_impedem_edicao(self):
        dados = self.dados()
        self.confirmar(descricao="Edição inicial para testar versão.")
        with self.assertRaisesMessage(ValidationError, "alterada por outro"):
            editar_servico(**dados)
        self.ordem.refresh_from_db()
        concluir_os(ordem_id=self.ordem.pk, resultado="reparado", descricao="Testado", usuario=self.usuario, chave_confirmacao=uuid.uuid4(), versao=self.ordem.versao)
        with self.assertRaisesMessage(ValidationError, "antes de concluir"):
            editar_servico(**self.dados())
        self.ordem.refresh_from_db()
        encerrar_os(ordem_id=self.ordem.pk, recebido_por="Pessoa B", para_baixa=False, usuario=self.usuario, chave_confirmacao=uuid.uuid4(), versao=self.ordem.versao)
        with self.assertRaises(ValidationError):
            editar_servico(**self.dados())

    def test_falha_no_movimento_reverte_revisao_e_configuracao(self):
        dados = self.dados(itens=[self.item(quantidade=2)])
        previa, _ = editar_servico(**dados)
        with patch.object(MovimentoEstoque, "save", side_effect=ValidationError("Falha simulada")), self.assertRaises(ValidationError):
            editar_servico(**dados, previa=previa)
        self.assertEqual(self.quantidade(), 2)
        self.assertEqual(self.saldo(), 3)
        self.assertFalse(RevisaoServico.objects.exists())
        self.assertFalse(IntervencaoComponente.objects.filter(revisao_os__isnull=False).exists())

    def test_edicao_por_outro_tecnico_esta_no_filtro_de_participacao(self):
        outro = get_user_model().objects.create_user(username="editor_da_os", first_name="Outro técnico")
        self.confirmar(usuario=outro)
        self.assertEqual(list(filtrar_ordens(ordens_para_consulta(), {"tecnico":outro})), [self.ordem])

    def test_historico_append_only_e_pecas_efetivas_no_formulario(self):
        revisao = self.confirmar()
        with self.assertRaises(ValidationError): revisao.save()
        with self.assertRaises(ValidationError): revisao.delete()
        self.assertEqual(len(itens_do_servico(self.registro)), 2)
        self.client.force_login(self.usuario)
        resposta = self.client.get(reverse("ordens:detalhar", args=[self.ordem.pk]))
        self.assertContains(resposta, "Ver histórico das edições deste serviço")
        self.assertContains(resposta, "Situação atual do ativo")
        self.assertNotContains(resposta, 'class="ram-preview"')

    def test_http_previa_assinatura_csrf_usuario_e_reenvio(self):
        url = reverse("ordens:servico_editar", args=[self.ordem.pk,self.registro.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.usuario)
        dados = {"descricao":"Troca da RAM com retirada da defeituosa", "justificativa":"Retirada esquecida", "versao":2, "chave_confirmacao":str(uuid.uuid4()),
            "pecas-TOTAL_FORMS":2,"pecas-INITIAL_FORMS":1,"pecas-MIN_NUM_FORMS":0,"pecas-MAX_NUM_FORMS":50,
            "pecas-0-componente":self.componentes["ram"].pk,"pecas-0-acao":"instalar","pecas-0-quantidade":1,
            "pecas-1-componente":self.componentes["ram"].pk,"pecas-1-acao":"retirar_sem_retorno","pecas-1-quantidade":1}
        resposta = self.client.post(url,dados)
        self.assertEqual(resposta.status_code,200)
        token = resposta.context["token"]
        self.assertFalse(RevisaoServico.objects.exists())
        protegido=Client(enforce_csrf_checks=True);protegido.force_login(self.usuario)
        self.assertEqual(protegido.post(url,{"confirmacao":token}).status_code,403)
        outro=get_user_model().objects.create_user(username="outro_editor")
        self.client.force_login(outro)
        self.assertContains(self.client.post(url,{"confirmacao":token}),"inválida")
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.post(url,{"confirmacao":token}).status_code,302)
        self.assertEqual(self.client.post(url,{"confirmacao":token}).status_code,302)
        self.assertEqual(self.quantidade(),1)
        self.assertEqual(self.saldo(),3)


class ConcorrenciaEdicaoTests(TransactionTestCase):
    def test_duas_edicoes_da_mesma_os_nao_movimentam_duas_vezes(self):
        usuario, categoria, departamento, componentes=preparar()
        ativo=novo_ativo(usuario,categoria,departamento,componentes)
        ordem=abrir_os(ativo_id=ativo.pk,entregue_por="Pessoa A",problema="Teste",usuario=usuario,chave_confirmacao=uuid.uuid4())[0]
        registro=registrar_servico(ordem_id=ordem.pk,descricao="Texto inicial",itens=[],usuario=usuario,chave_confirmacao=uuid.uuid4(),versao=1)[0]
        dados={"ordem_id":ordem.pk,"registro_id":registro.pk,"descricao":"Texto corrigido","justificativa":"Erro de digitação","itens":[],"usuario":usuario,"chave_confirmacao":uuid.uuid4(),"versao":2}
        previa,_=editar_servico(**dados)
        barreira=Barrier(2)
        def executar(_):
            close_old_connections()
            try:
                u=get_user_model().objects.get(pk=usuario.pk);barreira.wait(timeout=10)
                return editar_servico(**{**dados,"usuario":u},previa=previa)[1]
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:resultados=list(pool.map(executar,range(2)))
        self.assertCountEqual(resultados,[True,False])
        self.assertEqual(RevisaoServico.objects.count(),1)

    def test_edicoes_de_duas_os_disputando_ultima_peca_nao_geram_saldo_negativo(self):
        usuario,categoria,departamento,componentes=preparar()
        registrar_entrada(componente_id=componentes["ram"].pk,quantidade=1,origem="compra",data=timezone.localdate(),usuario=usuario,chave_confirmacao=uuid.uuid4())
        trabalhos=[]
        for n in range(2):
            ativo=novo_ativo(usuario,categoria,departamento,componentes,dti=f"DISPUTA-{n}")
            ordem=abrir_os(ativo_id=ativo.pk,entregue_por="Pessoa A",problema="Teste",usuario=usuario,chave_confirmacao=uuid.uuid4())[0]
            registro=registrar_servico(ordem_id=ordem.pk,descricao="Diagnóstico",itens=[],usuario=usuario,chave_confirmacao=uuid.uuid4(),versao=1)[0]
            dados={"ordem_id":ordem.pk,"registro_id":registro.pk,"descricao":"Memória aplicada","justificativa":"Aplicação esquecida","itens":[{"componente_id":componentes["ram"].pk,"acao":"instalar","quantidade":1}],"usuario":usuario,"chave_confirmacao":uuid.uuid4(),"versao":2}
            previa,_=editar_servico(**dados)
            trabalhos.append((dados,previa))
        barreira=Barrier(2)
        def executar(i):
            close_old_connections()
            try:
                u=get_user_model().objects.get(pk=usuario.pk);barreira.wait(timeout=10)
                d,p=trabalhos[i]
                editar_servico(**{**d,"usuario":u},previa=p)
                return "confirmado"
            except ValidationError:return "rejeitado"
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:r=list(pool.map(executar,range(2)))
        self.assertCountEqual(r,["confirmado","rejeitado"])
        self.assertEqual(componentes_com_saldo().get(pk=componentes["ram"].pk).saldo,0)
        self.assertEqual(RevisaoServico.objects.count(),1)
