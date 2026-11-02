from datetime import timedelta
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ativos.models import Ativo, ComponenteInstalado, IntervencaoComponente
from ativos.services import cadastrar_ativo
from ativos.tests_integracao import preparar_cadastros
from baixas.models import BaixaAtivo
from baixas.services import baixar_ativo
from cadastros.services import salvar_categoria, salvar_departamento
from estoque.models import Componente, MovimentoEstoque
from estoque.services import registrar_entrada
from movimentacoes.models import EmprestimoAtivo, TransferenciaAtivo
from movimentacoes.services import emprestar_ativo, transferir_ativo
from ordens.models import OrdemServico, RegistroAtendimento
from ordens.services import abrir_os, registrar_servico, atualizar_andamento
from .apresentacao import linha
from .definicoes import RELATORIOS
from .forms import formulario
from .pdf import gerar_pdf_relatorio
from .selectors import consultar, pendencias_operacionais


class RelatoriosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario, cls.categoria, cls.departamento, cls.componentes = preparar_cadastros()
        cls.outro = get_user_model().objects.create_user(username="tecnico_participante", first_name="Técnico", last_name="Dois")
        cls.destino = salvar_departamento(nome="Financeiro")
        cls.nobreak = salvar_categoria(nome="Nobreak")
        cls.pc = cadastrar_ativo(dados={"dti": "REL-0010", "patrimonio": "PAT-REL-0010", "modelo": "OptiPlex relatório",
            "categoria_id": cls.categoria.pk, "departamento_id": cls.departamento.pk},
            itens=[{"componente_id": c.pk, "quantidade": 1, "origem": "no_equipamento"} for c in cls.componentes.values()],
            especificacoes={"hostname": "PC-RH-RELATORIO", "sistema_operacional": "Windows 11 Pro"}, extras=[], usuario=cls.usuario, chave_confirmacao=uuid.uuid4())[0]
        cls.ordem = abrir_os(ativo_id=cls.pc.pk, problema="Não liga", entregue_por="Motorista A", usuario=cls.usuario, chave_confirmacao=uuid.uuid4())[0]
        registrar_servico(ordem_id=cls.ordem.pk, descricao="Diagnóstico", itens=[], usuario=cls.outro, chave_confirmacao=uuid.uuid4(), versao=1)
        cls.ordem.refresh_from_db()
        atualizar_andamento(ordem_id=cls.ordem.pk, descricao="Aguardar compra", status="aguardando_peca", usuario=cls.outro,
                            chave_confirmacao=uuid.uuid4(), versao=cls.ordem.versao)
        cls.emprestado = cls.novo_nobreak("REL-0020")
        cls.emprestimo = emprestar_ativo(ativo_id=cls.emprestado.pk, destino_id=cls.destino.pk, motivo="Substituição",
            recebido_por="Pessoa B", usuario=cls.usuario, chave_confirmacao=uuid.uuid4(), versao=1)[0]
        transferido = cls.novo_nobreak("REL-0030")
        cls.transferencia = transferir_ativo(ativo_id=transferido.pk, destino_id=cls.destino.pk, motivo="Demanda", usuario=cls.usuario,
                                           chave_confirmacao=uuid.uuid4(), versao=1)[0]
        baixado = cls.novo_nobreak("REL-0040")
        dados = dict(ativo_id=baixado.pk, motivo="Obsoleto", itens=[], usuario=cls.usuario, chave_confirmacao=uuid.uuid4(), versao=1)
        previa, _ = baixar_ativo(**dados)
        cls.baixa = baixar_ativo(**dados, previa=previa)[0]
        for tipo, qtd in (("ram", 5), ("fonte", 50)):
            registrar_entrada(componente_id=cls.componentes[tipo].pk, quantidade=qtd, origem="compra", data=timezone.localdate(),
                             usuario=cls.usuario, chave_confirmacao=uuid.uuid4())
        Componente.objects.filter(pk=cls.componentes["ram"].pk).update(quantidade_minima=10)
        Componente.objects.filter(pk=cls.componentes["processador"].pk).update(acompanhar_estoque=False)
        Componente.objects.filter(pk=cls.componentes["ssd"].pk).update(ativo=False)

    @classmethod
    def novo_nobreak(cls, dti):
        return cadastrar_ativo(dados={"dti": dti, "modelo": "Nobreak relatório", "categoria_id": cls.nobreak.pk,
                                     "departamento_id": cls.departamento.pk, "situacao": "reserva"},
            itens=[], especificacoes={}, extras=[], usuario=cls.usuario, chave_confirmacao=uuid.uuid4())[0]

    def consulta(self, tipo, **filtros):
        form = formulario(tipo, filtros)
        self.assertTrue(form.is_valid(), form.errors)
        return consultar(tipo, form.cleaned_data)

    def test_ativos_filtram_modelo_hostname_departamento_e_situacao(self):
        for filtros in ({"q": "RH-RELATORIO"}, {"q": "opti"}, {"q": "PAT-REL-0010"}, {"situacao": "em_manutencao"}):
            with self.subTest(filtros=filtros):
                self.assertEqual(list(self.consulta("ativos", **filtros)), [self.pc])
        self.assertEqual(self.consulta("ativos", departamento=self.destino.pk).count(), 1)
        self.assertEqual(list(self.consulta("ativos", emprestado="sim")), [self.emprestado])

    def test_ativo_emprestado_mostra_destino_temporario_sem_mudar_vinculo(self):
        registro = self.consulta("ativos", emprestado="sim").get()
        celulas = linha("ativos", registro)["celulas"]
        self.assertEqual(celulas[2], self.departamento.nome)
        self.assertIn(self.destino.nome, celulas[3])

    def test_os_filtra_tecnico_participante_sem_duplicar(self):
        self.assertEqual(list(self.consulta("ordens", tecnico=self.outro.pk)), [self.ordem])
        self.assertEqual(list(self.consulta("ordens", status="abertas")), [self.ordem])
        self.assertEqual(list(self.consulta("ordens", q="PC-RH")), [self.ordem])
        self.assertEqual(list(self.consulta("ordens", q="OptiPlex")), [self.ordem])

    def test_periodo_da_os_refere_se_a_abertura(self):
        ontem = timezone.localdate() - timedelta(days=1)
        hoje = timezone.localdate()
        self.assertEqual(self.consulta("ordens", inicio=hoje, fim=hoje).count(), 1)
        self.assertEqual(self.consulta("ordens", fim=ontem).count(), 0)

    def test_os_preserva_nome_do_departamento_da_epoca(self):
        nome = self.ordem.nome_departamento
        self.departamento.nome = "Departamento renomeado"
        self.departamento.save()
        registro = self.consulta("ordens").get()
        self.assertEqual(linha("ordens", registro)["celulas"][2], nome)

    def test_estoque_exclui_catalogo_sem_controle_mantem_zero_e_saldo_integral(self):
        consulta = self.consulta("estoque")
        self.assertFalse(consulta.filter(pk=self.componentes["processador"].pk).exists())
        self.assertEqual(consulta.get(pk=self.componentes["placa_mae"].pk).saldo, 0)
        self.assertEqual(consulta.get(pk=self.componentes["ram"].pk).saldo, 5)
        self.assertEqual(consulta.get(pk=self.componentes["fonte"].pk).saldo, 50)

    def test_estoque_baixo_respeita_minimo_e_inativacao(self):
        consulta = self.consulta("estoque", baixo="on")
        self.assertTrue(consulta.filter(pk=self.componentes["ram"].pk).exists())
        self.assertFalse(consulta.filter(pk=self.componentes["fonte"].pk).exists())
        self.assertFalse(consulta.filter(pk=self.componentes["ssd"].pk).exists())
        self.assertEqual(self.consulta("estoque", situacao="inativos").count(), 1)

    def test_transferencias_e_baixas_preservam_departamentos_originais(self):
        self.departamento.nome = "Novo nome"
        self.departamento.save()
        self.assertEqual(linha("transferencias", self.consulta("transferencias").get())["celulas"][2], self.transferencia.nome_origem)
        self.assertEqual(linha("baixas", self.consulta("baixas").get())["celulas"][2], self.baixa.nome_departamento)

    def test_movimentacoes_filtram_destino_periodo_e_situacao(self):
        self.assertEqual(list(self.consulta("emprestimos", situacao="abertos", destino=self.destino.pk)), [self.emprestimo])
        self.assertEqual(self.consulta("emprestimos", situacao="baixados").count(), 0)
        self.assertEqual(self.consulta("transferencias", fim=timezone.localdate()-timedelta(days=1)).count(), 0)
        self.assertEqual(self.consulta("baixas", departamento=self.departamento.pk).count(), 1)

    def test_seis_consultas_e_pdfs_exigem_login_e_get(self):
        for tipo in RELATORIOS:
            for nome in ("consultar", "imprimir"):
                url = reverse("relatorios:"+nome, args=[tipo])
                self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.usuario)
        for tipo in RELATORIOS:
            for nome in ("consultar", "imprimir"):
                url = reverse("relatorios:"+nome, args=[tipo])
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200)
                self.assertIn("no-store", r["Cache-Control"])
                self.assertEqual(self.client.post(url).status_code, 405)
                if nome == "imprimir":
                    self.assertTrue(r.content.startswith(b"%PDF"))
                    self.assertEqual(r["Content-Type"], "application/pdf")

    def test_filtro_invalido_nao_exporta_uma_consulta_mais_ampla(self):
        self.client.force_login(self.usuario)
        for tipo, filtros in (("ordens", {"inicio":"2026-12-31", "fim":"2026-01-01"}),
                              ("ativos", {"departamento":999999}), ("estoque", {"tipo":"inventado"})):
            r = self.client.get(reverse("relatorios:imprimir", args=[tipo]), filtros)
            self.assertEqual(r.status_code, 400)
            self.assertNotEqual(r["Content-Type"], "application/pdf")
            self.assertContains(r, "Confira os filtros", status_code=400)

    def test_relatorio_desconhecido_nao_cai_em_outro_tipo(self):
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.get("/relatorios/inventado/").status_code, 404)
        self.assertEqual(self.client.get("/relatorios/inventado/pdf/").status_code, 404)

    def test_exportacao_inclui_todas_paginas_e_descreve_filtros(self):
        for n in range(17): self.novo_nobreak(f"REL-EXTRA-{n:03d}")
        self.client.force_login(self.usuario)
        filtros = {"categoria":self.nobreak.pk, "page":2}
        r = self.client.get(reverse("relatorios:consultar", args=["ativos"]), filtros)
        self.assertEqual(r.context["page_obj"].paginator.count, 20)
        self.assertEqual(len(r.context["linhas"]), 5)
        with patch("relatorios.pdf.gerar_pdf_relatorio", return_value=b"%PDF-exemplo") as gerar:
            self.client.get(reverse("relatorios:imprimir", args=["ativos"]), filtros)
        self.assertEqual(len(gerar.call_args.kwargs["linhas"]), 20)
        self.assertEqual(gerar.call_args.kwargs["filtros"], ["Categoria: Nobreak"])

    def test_consulta_e_pdf_nao_alteram_dados_operacionais(self):
        modelos = [Ativo, ComponenteInstalado, IntervencaoComponente, Componente, MovimentoEstoque,
                   OrdemServico, RegistroAtendimento, TransferenciaAtivo, EmprestimoAtivo, BaixaAtivo]
        def dados():
            return {m.__name__:list(m.objects.order_by("pk").values()) for m in modelos}
        antes = dados()
        self.client.force_login(self.usuario)
        for tipo in RELATORIOS:
            self.client.get(reverse("relatorios:consultar", args=[tipo]))
            self.client.get(reverse("relatorios:imprimir", args=[tipo]))
        self.assertEqual(dados(), antes)

    def test_resultado_vazio_pode_gerar_pdf_sem_fabricar_dados(self):
        self.client.force_login(self.usuario)
        for tipo in RELATORIOS:
            with patch("relatorios.pdf.gerar_pdf_relatorio", return_value=b"%PDF-vazio") as gerar:
                r = self.client.get(reverse("relatorios:imprimir", args=[tipo]), {"q":"nao-existe-987654321"})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(gerar.call_args.kwargs["linhas"], [])

    def test_home_resume_pendencias_reais_com_atalhos(self):
        p = pendencias_operacionais()
        self.assertEqual(p["aguardando_peca"], 1)
        self.assertEqual(p["aguardando_coleta"], 0)
        self.assertEqual(p["emprestimos_abertos"], 1)
        self.assertEqual(p["estoque_baixo"], 2)
        self.assertEqual(p["os_abertas"], 1)
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("inicio"))
        self.assertContains(r, "Acompanhar pendências")
        self.assertContains(r, reverse("relatorios:consultar", args=["estoque"])+"?baixo=on")
        # O total inclui os recortes de peça/coleta e exclui apenas encerradas.
        from ordens.selectors import filtrar_ordens
        for status in ("aberta", "em_atendimento", "aguardando_peca"):
            with self.subTest(status=status):
                OrdemServico.objects.filter(pk=self.ordem.pk).update(status=status)
                total = pendencias_operacionais()["os_abertas"]
                self.assertEqual(total, 1)
                self.assertEqual(total, filtrar_ordens(OrdemServico.objects.all(), {"status": "abertas"}).count())
        from ordens.services import concluir_os, encerrar_os
        self.ordem.refresh_from_db()
        concluir_os(ordem_id=self.ordem.pk, resultado="reparado", descricao="Testes concluídos", usuario=self.usuario,
                    chave_confirmacao=uuid.uuid4(), versao=self.ordem.versao)
        self.assertEqual(pendencias_operacionais()["os_abertas"], 1)
        self.assertEqual(pendencias_operacionais()["aguardando_coleta"], 1)
        self.ordem.refresh_from_db()
        encerrar_os(ordem_id=self.ordem.pk, recebido_por="Pessoa recebedora", para_baixa=False, usuario=self.usuario,
                    chave_confirmacao=uuid.uuid4(), versao=self.ordem.versao)
        self.assertEqual(pendencias_operacionais()["os_abertas"], 0)
        self.assertEqual(filtrar_ordens(OrdemServico.objects.all(), {"status": "abertas"}).count(), 0)

    def test_pdf_com_celula_maior_que_pagina_e_filtros_escapados(self):
        valores = ["<peça> & configuração "*500, "RAM", "1", "0", "Regular"]
        b = gerar_pdf_relatorio(definicao=RELATORIOS["estoque"], linhas=[valores], filtros=["Pesquisa: <teste> & relatório"],
                               emitido_em=timezone.now(), emitido_por="Técnico de TI")
        self.assertTrue(b.startswith(b"%PDF"))
