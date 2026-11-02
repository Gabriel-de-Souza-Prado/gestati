from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from ativos.alteracoes import alterar_configuracao
from ativos.models import Ativo
from ativos.services import cadastrar_ativo
from cadastros.services import excluir_departamento, salvar_categoria, salvar_departamento
from ordens.services import abrir_os
from .models import EmprestimoAtivo, TransferenciaAtivo
from .pdf import gerar_pdf_transferencia
from .selectors import filtrar_movimentacoes
from .services import devolver_emprestimo, emprestar_ativo, transferir_ativo


def preparar():
    u = get_user_model().objects.create_user(username="ti_movimentacoes")
    origem = salvar_departamento(nome="Diretoria de TI", sigla="DTI")
    destino = salvar_departamento(nome="Saúde", sigla="SMS")
    categoria = salvar_categoria(nome="Nobreak")
    ativo, _ = cadastrar_ativo(dados={"dti":"MOV-0010", "modelo":"Nobreak de teste", "categoria_id":categoria.pk, "departamento_id":origem.pk, "situacao":"reserva"}, itens=[], especificacoes={}, extras=[], usuario=u, chave_confirmacao=uuid.uuid4())
    return u, origem, destino, ativo


class MovimentacoesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario, cls.origem, cls.destino, cls.ativo = preparar()

    def dados(self, **alteracoes):
        self.ativo.refresh_from_db()
        return {"ativo_id":self.ativo.pk, "destino_id":self.destino.pk, "motivo":"Atender demanda da unidade", "usuario":self.usuario, "chave_confirmacao":uuid.uuid4(), "versao":self.ativo.versao, **alteracoes}

    def emprestar(self, **alteracoes):
        return emprestar_ativo(**self.dados(), recebido_por="Motorista A", **alteracoes)[0]

    def devolver(self, emprestimo, **alteracoes):
        self.ativo.refresh_from_db()
        return devolver_emprestimo(**{"emprestimo_id":emprestimo.pk,"devolvido_por":"Motorista B","usuario":self.usuario,"chave_confirmacao":uuid.uuid4(),"versao":self.ativo.versao,**alteracoes})

    def test_transferencia_atualiza_vinculo_sem_mudar_situacao_ou_estoque(self):
        from estoque.models import MovimentoEstoque
        registro, criado = transferir_ativo(**self.dados())
        self.ativo.refresh_from_db()
        self.assertTrue(criado)
        self.assertEqual(self.ativo.departamento_id,self.destino.pk)
        self.assertEqual(self.ativo.situacao,"reserva")
        self.assertEqual(registro.origem_id,self.origem.pk)
        self.assertFalse(MovimentoEstoque.objects.exists())

    def test_transferencia_reenvio_e_payload_diferente(self):
        dados=self.dados()
        um,_=transferir_ativo(**dados)
        dois,criado=transferir_ativo(**dados)
        self.assertFalse(criado); self.assertEqual(um.pk,dois.pk)
        with self.assertRaisesMessage(ValidationError,"outros dados"):
            transferir_ativo(**{**dados,"motivo":"Outro motivo"})

    def test_destino_igual_inativo_e_motivo_vazio_rejeitados(self):
        for mudanca in ({"destino_id":self.origem.pk},{"motivo":" "}):
            with self.subTest(mudanca=mudanca), self.assertRaises(ValidationError):
                transferir_ativo(**self.dados(**mudanca))
        self.destino.ativo=False; self.destino.save()
        with self.assertRaises(ValidationError):
            transferir_ativo(**self.dados())
        self.assertFalse(TransferenciaAtivo.objects.exists())

    def test_formulario_antigo_nao_transfere_apos_outro_evento(self):
        dados=self.dados()
        transferencia,_=transferir_ativo(**dados)
        with self.assertRaisesMessage(ValidationError,"ativo mudou"):
            transferir_ativo(**{**dados,"chave_confirmacao":uuid.uuid4(),"destino_id":self.origem.pk})

    def test_historico_e_pdf_preservam_identificadores_e_nomes(self):
        registro,_=transferir_ativo(**self.dados())
        salvar_departamento(nome="Saúde renomeada",sigla="SMS",departamento_id=self.destino.pk)
        Ativo.objects.filter(pk=self.ativo.pk).update(dti="NOVO-DTI")
        registro.refresh_from_db()
        self.assertEqual(registro.nome_destino,"Saúde")
        self.assertEqual(registro.dti_ativo,"MOV-0010")
        pdf=gerar_pdf_transferencia(registro)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf),10000)
        with self.assertRaises(ValidationError):
            registro.delete()
        with self.assertRaises(ValidationError):
            excluir_departamento(departamento_id=self.origem.pk)

    def test_emprestimo_preserva_departamento_e_situacao(self):
        e=self.emprestar(); self.ativo.refresh_from_db()
        self.assertEqual(self.ativo.departamento_id,self.origem.pk)
        self.assertEqual(self.ativo.situacao,"reserva")
        self.assertEqual(e.destino_id,self.destino.pk)
        self.assertEqual(e.recebido_por,"Motorista A")
        self.assertFalse(self.ativo.ordens_servico.exists())

    def test_emprestimo_reenvio_apos_devolucao_nao_cria_outro(self):
        dados=self.dados(); dados["recebido_por"]="Motorista A"
        e,_=emprestar_ativo(**dados)
        self.devolver(e)
        repetido,criado=emprestar_ativo(**dados)
        self.assertFalse(criado); self.assertEqual(e.pk,repetido.pk)
        self.assertEqual(EmprestimoAtivo.objects.count(),1)

    def test_emprestimo_ativo_bloqueia_outro_os_e_pecas(self):
        self.emprestar()
        with self.assertRaisesMessage(ValidationError,"emprestado"):
            self.emprestar()
        with self.assertRaisesMessage(ValidationError,"emprestado"):
            abrir_os(ativo_id=self.ativo.pk,entregue_por="Técnico",problema="Falha",usuario=self.usuario,chave_confirmacao=uuid.uuid4())
        self.ativo.refresh_from_db()
        from estoque.services import salvar_componente
        p=salvar_componente(nome="Bateria de teste",tipo="outro")
        with self.assertRaisesMessage(ValidationError,"emprestado"):
            alterar_configuracao(ativo_id=self.ativo.pk,tipo="fisica",justificativa="Troca",usuario=self.usuario,chave_confirmacao=uuid.uuid4(),versao=self.ativo.versao,itens=[{"componente_id":p.pk,"quantidade":1,"acao":"instalar"}])

    def test_os_aberta_impede_transferencia_e_emprestimo(self):
        abrir_os(ativo_id=self.ativo.pk,entregue_por="Técnico",problema="Falha",usuario=self.usuario,chave_confirmacao=uuid.uuid4())
        for servico in (transferir_ativo,emprestar_ativo):
            with self.subTest(servico=servico.__name__), self.assertRaises(ValidationError):
                servico(**self.dados(),**({"recebido_por":"Pessoa A"} if servico is emprestar_ativo else {}))

    def test_indisponivel_nao_transfere_ou_empresta(self):
        for situacao in ("baixado","sem_reparo","em_manutencao"):
            Ativo.objects.filter(pk=self.ativo.pk).update(situacao=situacao)
            for servico in (transferir_ativo,emprestar_ativo):
                with self.subTest(situacao=situacao,servico=servico.__name__), self.assertRaises(ValidationError):
                    servico(**self.dados(),**({"recebido_por":"Pessoa A"} if servico is emprestar_ativo else {}))

    def test_devolucao_por_outra_pessoa_identifica_tecnico(self):
        e=self.emprestar(); self.devolver(e)
        e.refresh_from_db(); self.ativo.refresh_from_db()
        self.assertEqual(e.devolvido_por,"Motorista B")
        self.assertEqual(e.recebido_devolucao_por_id,self.usuario.pk)
        self.assertEqual(self.ativo.departamento_id,self.origem.pk)
        self.assertFalse(self.ativo.emprestimos.filter(encerrado_em__isnull=True).exists())
        novo=self.emprestar(); self.assertNotEqual(e.pk,novo.pk)

    def test_devolucao_reenvio_e_nome_obrigatorio(self):
        e=self.emprestar(); self.ativo.refresh_from_db()
        dados={"emprestimo_id":e.pk,"devolvido_por":"Motorista B","usuario":self.usuario,"chave_confirmacao":uuid.uuid4(),"versao":self.ativo.versao}
        self.assertTrue(devolver_emprestimo(**dados)[1])
        self.assertFalse(devolver_emprestimo(**dados)[1])
        with self.assertRaisesMessage(ValidationError,"outros dados"):
            devolver_emprestimo(**{**dados,"devolvido_por":"Outra pessoa"})
        with self.assertRaises(ValidationError):
            self.devolver(e,devolvido_por=" ")
        with self.assertRaisesMessage(ValidationError,"já foi encerrado"):
            self.devolver(e)

    def test_banco_impede_emprestimos_simultaneos_e_devolucao_incompleta(self):
        e=self.emprestar()
        dados={f.attname:getattr(e,f.attname) for f in EmprestimoAtivo._meta.fields if not f.primary_key}
        dados["chave_confirmacao"]=uuid.uuid4()
        with self.assertRaises(IntegrityError),transaction.atomic():
            EmprestimoAtivo.objects.create(**dados)
        with self.assertRaises(IntegrityError),transaction.atomic():
            EmprestimoAtivo.objects.filter(pk=e.pk).update(devolvido_em=timezone.now())

    def test_busca_e_filtros_de_movimentacoes(self):
        e=self.emprestar()
        consulta=EmprestimoAtivo.objects.all()
        self.assertEqual(list(filtrar_movimentacoes(consulta,{"q":"MOV-0010","situacao":"abertos","inicio":timezone.localdate(),"fim":timezone.localdate(),"destino":self.destino})),[e])
        self.devolver(e)
        self.assertFalse(filtrar_movimentacoes(consulta,{"situacao":"abertos"}).exists())

    def test_acesso_csrf_metodos_e_pdf_sem_mutacao(self):
        t,_=transferir_ativo(**self.dados())
        rotas=[reverse("movimentacoes:listar"),reverse("movimentacoes:selecionar",args=["transferencias"]),reverse("movimentacoes:registrar",args=["transferencias",self.ativo.pk]),reverse("movimentacoes:detalhar",args=["transferencias",t.pk]),reverse("movimentacoes:imprimir",args=[t.pk])]
        for url in rotas:
            self.assertEqual(self.client.get(url).status_code,302)
        cliente=Client(enforce_csrf_checks=True); cliente.force_login(self.usuario)
        self.assertEqual(cliente.post(rotas[2],{}).status_code,403)
        self.assertEqual(cliente.post(rotas[-1],{}).status_code,403)
        r=cliente.get(rotas[-1]); self.assertEqual(r["Content-Type"],"application/pdf"); self.assertIn("no-store",r["Cache-Control"])
        self.assertEqual(TransferenciaAtivo.objects.count(),1)

    def test_http_transferencia_emprestimo_devolucao_e_ficha(self):
        self.client.force_login(self.usuario)
        url=reverse("movimentacoes:registrar",args=["emprestimos",self.ativo.pk])
        r=self.client.post(url,{"destino":self.destino.pk,"motivo":"Atender unidade","recebido_por":"Ana","versao":self.ativo.versao,"chave_confirmacao":uuid.uuid4()})
        self.assertEqual(r.status_code,302)
        e=EmprestimoAtivo.objects.get(); self.ativo.refresh_from_db()
        ficha=self.client.get(reverse("ativos:ativo_detalhar",args=[self.ativo.pk]))
        self.assertContains(ficha,"Equipamento emprestado para Saúde")
        self.assertNotContains(ficha,"Abrir OS deste ativo")
        self.assertNotContains(ficha,"Alterar configuração")
        self.assertEqual(self.client.post(reverse("movimentacoes:devolver",args=[e.pk]),{"devolvido_por":"Bruno","versao":self.ativo.versao,"chave_confirmacao":uuid.uuid4()}).status_code,302)
        self.ativo.refresh_from_db()
        r=self.client.post(reverse("movimentacoes:registrar",args=["transferencias",self.ativo.pk]),{"destino":self.destino.pk,"motivo":"Redistribuição permanente","versao":self.ativo.versao,"chave_confirmacao":uuid.uuid4()})
        self.assertEqual(r.status_code,302)

    def test_transferencia_torna_emprestimo_definitivo_sem_devolucao_ficticia(self):
        e=self.emprestar()
        t,_=transferir_ativo(**self.dados())
        e.refresh_from_db(); self.ativo.refresh_from_db()
        self.assertEqual(e.encerramento,"transferencia")
        self.assertEqual(e.transferencia_definitiva_id,t.pk)
        self.assertIsNotNone(e.encerrado_em)
        self.assertIsNone(e.devolvido_em)
        self.assertEqual(e.devolvido_por,"")
        self.assertIsNone(e.recebido_devolucao_por_id)
        self.assertEqual(self.ativo.departamento_id,self.destino.pk)
        self.assertFalse(self.ativo.emprestimos.filter(encerrado_em__isnull=True).exists())
        with self.assertRaisesMessage(ValidationError,"já foi encerrado"):
            self.devolver(e)
        self.client.force_login(self.usuario)
        resposta=self.client.get(reverse("movimentacoes:detalhar",args=["emprestimos",e.pk]))
        self.assertContains(resposta,"Encerrado por transferência definitiva")
        self.assertNotContains(resposta,"Registrar devolução")

    def test_transferencia_invalida_nao_encerra_emprestimo(self):
        e=self.emprestar()
        with self.assertRaises(ValidationError):
            transferir_ativo(**self.dados(destino_id=self.origem.pk))
        e.refresh_from_db()
        self.assertIsNone(e.encerrado_em)
        self.assertFalse(TransferenciaAtivo.objects.exists())

    def test_pode_emprestar_em_uso_ou_reserva(self):
        Ativo.objects.filter(pk=self.ativo.pk).update(situacao="em_uso")
        e=self.emprestar(); self.ativo.refresh_from_db()
        self.assertEqual(self.ativo.situacao,"em_uso")
        self.devolver(e)
        Ativo.objects.filter(pk=self.ativo.pk).update(situacao="reserva")
        self.assertIsNotNone(self.emprestar().pk)



class ConcorrenciaMovimentacoesTests(TransactionTestCase):
    def test_transferencia_e_emprestimo_concorrentes_serializam_ativo(self):
        usuario,origem,destino,ativo=preparar(); barreira=Barrier(2)
        def executar(i):
            close_old_connections()
            try:
                u=get_user_model().objects.get(pk=usuario.pk); barreira.wait(timeout=10)
                d={"ativo_id":ativo.pk,"destino_id":destino.pk,"motivo":"Demanda","usuario":u,"chave_confirmacao":uuid.uuid4(),"versao":1}
                if i: emprestar_ativo(**d,recebido_por="Pessoa A")
                else: transferir_ativo(**d)
                return "confirmado"
            except ValidationError:
                return "rejeitado"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            r=list(pool.map(executar,range(2)))
        self.assertCountEqual(r,["confirmado","rejeitado"])
        self.assertEqual(TransferenciaAtivo.objects.count()+EmprestimoAtivo.objects.count(),1)

    def test_mesmo_emprestimo_concorrente_nao_duplica(self):
        usuario,origem,destino,ativo=preparar(); barreira=Barrier(2); chave=uuid.uuid4()
        def executar(_):
            close_old_connections()
            try:
                u=get_user_model().objects.get(pk=usuario.pk); barreira.wait(timeout=10)
                return emprestar_ativo(ativo_id=ativo.pk,destino_id=destino.pk,motivo="Demanda",recebido_por="Pessoa A",usuario=u,chave_confirmacao=chave,versao=1)[1]
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            r=list(pool.map(executar,range(2)))
        self.assertCountEqual(r,[True,False]); self.assertEqual(EmprestimoAtivo.objects.count(),1)


    def test_conversao_e_devolucao_concorrentes_encerram_uma_unica_vez(self):
        usuario,origem,destino,ativo=preparar()
        e,_=emprestar_ativo(ativo_id=ativo.pk,destino_id=destino.pk,motivo="Reserva temporária",recebido_por="Pessoa A",usuario=usuario,chave_confirmacao=uuid.uuid4(),versao=1)
        barreira=Barrier(2)
        def executar(i):
            close_old_connections()
            try:
                u=get_user_model().objects.get(pk=usuario.pk); barreira.wait(timeout=10)
                if i:
                    devolver_emprestimo(emprestimo_id=e.pk,devolvido_por="Pessoa B",usuario=u,chave_confirmacao=uuid.uuid4(),versao=2)
                    return "devolucao"
                transferir_ativo(ativo_id=ativo.pk,destino_id=destino.pk,motivo="Permanência definitiva",usuario=u,chave_confirmacao=uuid.uuid4(),versao=2)
                return "transferencia"
            except ValidationError:
                return "rejeitado"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            r=list(pool.map(executar,range(2)))
        self.assertEqual(r.count("rejeitado"),1)
        e.refresh_from_db()
        if "transferencia" in r:
            self.assertEqual(e.encerramento,"transferencia"); self.assertIsNone(e.devolvido_em)
            self.assertEqual(TransferenciaAtivo.objects.count(),1)
        else:
            self.assertEqual(e.encerramento,"devolucao"); self.assertIsNotNone(e.devolvido_em)
            self.assertEqual(TransferenciaAtivo.objects.count(),0)
