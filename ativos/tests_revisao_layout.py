import uuid
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from cadastros.services import salvar_categoria
from estoque.models import MovimentoEstoque
from .forms import AtivoForm
from .models import Ativo, AlteracaoConfiguracao, IntervencaoComponente
from .services import cadastrar_ativo, editar_dados_computador
from .tests_integracao import preparar_cadastros


class RevisaoEquipamentosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario, cls.categoria, cls.departamento, cls.componentes = preparar_cadastros()
        cls.nobreak = salvar_categoria(nome="Nobreak", perfil_configuracao="nobreak")

    def criar(self, codigo="REV-0010", computador=True):
        return cadastrar_ativo(dados={"dti": codigo, "modelo": "Revisão", "categoria_id": (self.categoria if computador else self.nobreak).pk,
            "departamento_id": self.departamento.pk}, itens=[{"componente_id":c.pk,"quantidade":1,"origem":"no_equipamento"} for c in self.componentes.values()] if computador else [],
            especificacoes={"hostname":"PC-ANTES","sistema_operacional":"Windows 10"} if computador else {}, extras=[], usuario=self.usuario, chave_confirmacao=uuid.uuid4())[0]

    def test_paginacao_dez_preserva_filtros_e_navegacao_numerada(self):
        for numero in range(23):
            self.criar(f"PAG-{numero:03}", computador=False)
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("ativos:ativo_listar"), {"q":"PAG-", "page":2})
        self.assertEqual(len(r.context["page_obj"]), 10)
        self.assertEqual(r.context["page_obj"].paginator.num_pages, 3)
        self.assertContains(r, "q=PAG-&amp;page=3")
        self.assertContains(r, 'aria-label="Página 2, atual"')
        self.assertEqual(len(self.client.get(reverse("ativos:ativo_listar"), {"q":"PAG-", "page":3}).context["page_obj"]), 3)

    def test_equipamento_sem_composicao_nao_oferece_nem_aceita_edicao_de_pecas(self):
        ativo = self.criar(computador=False)
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("ativos:ativo_detalhar", args=[ativo.pk]))
        self.assertNotContains(r, "Alterar configuração")
        self.assertNotContains(r, "Configuração atual")
        self.assertNotContains(r, "Configuração Inicial")
        for metodo in (self.client.get, self.client.post):
            self.assertEqual(metodo(reverse("ativos:configuracao_alterar", args=[ativo.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("ativos:ativo_editar", args=[ativo.pk])), "Alterar configuração")

    def test_editar_nome_e_so_pela_configuracao_nao_movimenta_pecas(self):
        ativo = self.criar()
        self.client.force_login(self.usuario)
        url = reverse("ativos:configuracao_alterar", args=[ativo.pk])
        self.assertContains(self.client.get(url), 'name="dados-hostname"')
        antes = list(ativo.componentes_instalados.values_list("componente_id","quantidade"))
        r = self.client.post(url, {"acao":"dados","versao_dados":ativo.versao,"dados-hostname":"PC-NOVO","dados-sistema_operacional":"Windows 11"})
        self.assertRedirects(r, url)
        ativo.refresh_from_db()
        self.assertEqual(ativo.especificacoes, {"hostname":"PC-NOVO","sistema_operacional":"Windows 11"})
        self.assertEqual(list(ativo.componentes_instalados.values_list("componente_id","quantidade")), antes)
        self.assertEqual(IntervencaoComponente.objects.count(),5)
        self.assertFalse(MovimentoEstoque.objects.exists())
        self.assertFalse(AlteracaoConfiguracao.objects.exists())

    def test_dados_computador_rejeitam_versao_antiga_campos_invalidos_e_outro_tipo(self):
        ativo = self.criar()
        editar_dados_computador(ativo_id=ativo.pk, especificacoes={"hostname":"NOVO"},versao=1,usuario=self.usuario)
        for especificacoes, versao in (({"hostname":"ANTIGO"},1), ({"hostname":"x"*161},2), ({"ram":32},2)):
            with self.subTest(versao=versao), self.assertRaises(ValidationError):
                editar_dados_computador(ativo_id=ativo.pk, especificacoes=especificacoes, versao=versao, usuario=self.usuario)
        ativo.refresh_from_db()
        self.assertEqual(ativo.especificacoes,{"hostname":"NOVO"})
        nobreak = self.criar("REV-NB",computador=False)
        with self.assertRaises(ValidationError):
            editar_dados_computador(ativo_id=nobreak.pk, especificacoes={}, versao=1, usuario=self.usuario)

    def test_dados_descritivos_podem_ser_atualizados_durante_os_sem_trocar_pecas(self):
        from ordens.services import abrir_os
        ativo = self.criar()
        os = abrir_os(ativo_id=ativo.pk,problema="Ajuste de software",entregue_por="Pessoa",usuario=self.usuario,chave_confirmacao=uuid.uuid4())[0]
        ativo.refresh_from_db()
        editar_dados_computador(ativo_id=ativo.pk,especificacoes={"sistema_operacional":"Windows 11"},versao=ativo.versao,usuario=self.usuario)
        os.refresh_from_db()
        self.assertEqual(os.status,"aberta")
        self.assertFalse(MovimentoEstoque.objects.exists())

    def test_periodo_de_garantia_exige_estado_e_datas_coerentes_sem_meses(self):
        base={"dti":"G-001","categoria":self.nobreak.pk,"departamento":self.departamento.pk,"situacao":"reserva","chave_confirmacao":str(uuid.uuid4())}
        self.assertNotIn("garantia_meses",AtivoForm().fields)
        for dados in ({"garantia":"nao_informada","inicio_garantia":"2026-01-01"},
                      {"garantia":"sem_garantia","fim_garantia":"2027-01-01"},
                      {"garantia":"com_garantia","inicio_garantia":"2026-01-01"},
                      {"garantia":"com_garantia","inicio_garantia":"2026-02-01","fim_garantia":"2026-01-01"}):
            with self.subTest(dados=dados): self.assertFalse(AtivoForm({**base,**dados}).is_valid())
        self.assertTrue(AtivoForm({**base,"garantia":"com_garantia","inicio_garantia":"2026-01-01","fim_garantia":"2027-01-01"}).is_valid())

    def test_linha_excluida_do_formset_nao_instala_nem_consume(self):
        self.client.force_login(self.usuario)
        dados={"dti":"FORM-DELETE","categoria":self.categoria.pk,"departamento":self.departamento.pk,"situacao":"reserva","garantia":"nao_informada","chave_confirmacao":str(uuid.uuid4())}
        for grupo,tipo in (("processador","processador"),("placa_mae","placa_mae"),("ram","ram"),("armazenamento","ssd"),("fonte","fonte"),("outro",None)):
            prefix=f"pecas-{grupo}"
            dados.update({f"{prefix}-TOTAL_FORMS":2 if grupo=="ram" else (1 if tipo else 0),f"{prefix}-INITIAL_FORMS":0})
            if tipo:
                dados.update({f"{prefix}-0-componente":self.componentes[tipo].pk,f"{prefix}-0-quantidade":1,f"{prefix}-0-origem":"no_equipamento",f"{prefix}-0-DELETE":"False"})
        # Simula a linha ocultada: campos desabilitados, somente DELETE enviado.
        dados["pecas-ram-1-DELETE"]="on"
        r=self.client.post(reverse("ativos:ativo_criar"),dados)
        self.assertEqual(r.status_code,302)
        ativo=Ativo.objects.get(dti="FORM-DELETE")
        self.assertEqual(ativo.componentes_instalados.get(componente=self.componentes["ram"]).quantidade,1)
        self.assertFalse(MovimentoEstoque.objects.exists())
