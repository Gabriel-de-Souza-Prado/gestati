from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from ativos.composicao import calcular_ram_total_gb
from ativos.models import Ativo, ComponenteInstalado, IntervencaoComponente
from ativos.services import cadastrar_ativo, editar_ativo, CAMPOS_ATIVO
from cadastros.services import salvar_categoria, salvar_departamento
from estoque.forms import EntradaEstoqueForm
from estoque.models import MovimentoEstoque
from estoque.selectors import componentes_com_saldo
from estoque.services import registrar_entrada, salvar_componente, registrar_retorno_intervencao
from .forms import PecaServicoForm
from .models import OrdemServico as OS, RegistroAtendimento as Registro
from .pdf import gerar_pdf_os
from .selectors import filtrar_ordens, ordens_para_consulta
from .services import abrir_os, atualizar_andamento, concluir_os, encerrar_os, registrar_servico


def preparar():
    usuario = get_user_model().objects.create_user(username="tecnico_os", password="SenhaDeTeste!123", first_name="Equipe TI")
    categoria = salvar_categoria(nome="Computador", perfil_configuracao="computador")
    departamento = salvar_departamento(nome="Saúde", sigla="SMS")
    componentes = {}
    for tipo in ("placa_mae", "processador", "ram", "fonte", "ssd"):
        capacidade = {"ram": 8, "ssd": 256}.get(tipo)
        componentes[tipo] = salvar_componente(nome=f"Exemplo {tipo}", tipo=tipo, capacidade=capacidade, unidade_capacidade="GB" if capacidade else "")
    return usuario, categoria, departamento, componentes


def novo_ativo(usuario, categoria, departamento, componentes, dti="OS-0010", **dados):
    return cadastrar_ativo(
        dados={"nome": "Computador de atendimento", "dti": dti, "categoria_id": categoria.pk, "departamento_id": departamento.pk, **dados},
        itens=[{"componente_id": c.pk, "quantidade": 1, "origem": "no_equipamento"} for c in componentes.values()],
        especificacoes={}, extras=[], usuario=usuario, chave_confirmacao=uuid.uuid4(),
    )[0]


class OrdensTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario, cls.categoria, cls.departamento, cls.componentes = preparar()
        cls.ativo = novo_ativo(cls.usuario, cls.categoria, cls.departamento, cls.componentes)

    def abrir(self, **alteracoes):
        return abrir_os(**{"ativo_id": self.ativo.pk, "entregue_por": "Motorista A", "problema": "Não liga.", "usuario": self.usuario, "chave_confirmacao": uuid.uuid4(), **alteracoes})

    def dados(self, ordem):
        ordem.refresh_from_db()
        return {"ordem_id": ordem.pk, "usuario": self.usuario, "chave_confirmacao": uuid.uuid4(), "versao": ordem.versao}

    def entrada(self, tipo, quantidade):
        return registrar_entrada(componente_id=self.componentes[tipo].pk, quantidade=quantidade, origem="compra", data=timezone.localdate(), usuario=self.usuario, chave_confirmacao=uuid.uuid4())

    def servico(self, ordem, itens=None, **alteracoes):
        return registrar_servico(**{**self.dados(ordem), "descricao": "Serviço e testes realizados.", "itens": itens or [], **alteracoes})

    def item(self, tipo="ram", acao="instalar", quantidade=1):
        return {"componente_id": self.componentes[tipo].pk, "acao": acao, "quantidade": quantidade}

    def concluir(self, ordem, resultado="reparado"):
        return concluir_os(**self.dados(ordem), resultado=resultado, descricao="Testado e verificado.")

    def encerrar(self, ordem, para_baixa=False):
        return encerrar_os(**self.dados(ordem), recebido_por="" if para_baixa else "Motorista B", para_baixa=para_baixa)

    def test_abertura_preserva_departamento_e_muda_situacao(self):
        ordem, criada = self.abrir()
        self.ativo.refresh_from_db()
        self.assertTrue(criada)
        self.assertEqual(ordem.status, "aberta")
        self.assertEqual(ordem.entregue_por, "Motorista A")
        self.assertEqual(self.ativo.situacao, "em_manutencao")
        self.assertEqual(self.ativo.departamento_id, self.departamento.pk)
        self.assertFalse(MovimentoEstoque.objects.exists())

    def test_abertura_repetida_retorna_a_mesma_os_e_rejeita_outro_payload(self):
        chave = uuid.uuid4()
        ordem, _ = self.abrir(chave_confirmacao=chave)
        outra, criada = self.abrir(chave_confirmacao=chave)
        self.assertFalse(criada)
        self.assertEqual(ordem.pk, outra.pk)
        with self.assertRaisesMessage(ValidationError, "outros dados"):
            self.abrir(chave_confirmacao=chave, problema="Outro problema")

    def test_uma_os_aberta_inclusive_aguardando_coleta(self):
        ordem, _ = self.abrir()
        self.concluir(ordem)
        with self.assertRaisesMessage(ValidationError, "já possui uma OS"):
            self.abrir()
        self.assertEqual(OS.objects.count(), 1)

    def test_banco_impede_outra_os_aberta(self):
        ordem, _ = self.abrir()
        dados = {f.attname: getattr(ordem, f.attname) for f in OS._meta.fields if not f.primary_key}
        dados["chave_abertura"] = uuid.uuid4()
        with self.assertRaises(IntegrityError), transaction.atomic():
            OS.objects.create(**dados)

    def test_nomes_e_problema_obrigatorios_e_sem_telefone(self):
        for alteracoes in ({"entregue_por": "  "}, {"problema": " "}):
            with self.subTest(alteracoes=alteracoes), self.assertRaises(ValidationError):
                self.abrir(**alteracoes)
        self.assertFalse(OS.objects.exists())

    def test_garantia_avisa_mas_permite_abertura(self):
        hoje = timezone.localdate()
        Ativo.objects.filter(pk=self.ativo.pk).update(garantia="com_garantia", inicio_garantia=hoje-timedelta(days=30), fim_garantia=hoje+timedelta(days=100))
        self.client.force_login(self.usuario)
        resposta = self.client.get(reverse("ordens:abrir", args=[self.ativo.pk]))
        self.assertContains(resposta, "não impede a abertura")
        ordem, _ = self.abrir()
        self.assertTrue(ordem.garantia_na_abertura)

    def test_baixado_nao_recebe_os(self):
        Ativo.objects.filter(pk=self.ativo.pk).update(situacao="baixado")
        with self.assertRaises(ValidationError):
            self.abrir()

    def test_andamento_aguarda_peca_sem_reservar_estoque(self):
        ordem, _ = self.abrir()
        atualizar_andamento(**self.dados(ordem), status="aguardando_peca", descricao="Falta fonte para substituir.")
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, "aguardando_peca")
        self.assertFalse(MovimentoEstoque.objects.exists())

    def test_servico_sem_pecas_nao_consume(self):
        ordem, _ = self.abrir()
        self.servico(ordem, descricao="Atualização do sistema operacional.")
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, "em_atendimento")
        self.assertFalse(MovimentoEstoque.objects.exists())

    def test_upgrade_de_8_para_16_atualiza_composicao_estoque_e_evento(self):
        self.entrada("ram", 2)
        ordem, _ = self.abrir()
        self.servico(ordem, [self.item()])
        instalados = list(self.ativo.componentes_instalados.select_related("componente"))
        self.assertEqual(calcular_ram_total_gb([(l.componente, l.quantidade) for l in instalados]), 16)
        self.assertEqual(componentes_com_saldo().get(pk=self.componentes["ram"].pk).saldo, 1)
        evento = ordem.registros.get().intervencoes.get()
        self.assertEqual(evento.movimento_estoque.tipo, "saida")
        self.assertEqual(evento.ativo_id, self.ativo.pk)

    def test_troca_mesma_especificacao_retira_defeituosa_sem_retorno(self):
        self.entrada("fonte", 1)
        ordem, _ = self.abrir()
        self.servico(ordem, [self.item("fonte", "retirar_sem_retorno"), self.item("fonte")])
        self.assertEqual(self.ativo.componentes_instalados.get(componente=self.componentes["fonte"]).quantidade, 1)
        self.assertEqual(componentes_com_saldo().get(pk=self.componentes["fonte"].pk).saldo, 0)
        self.assertFalse(MovimentoEstoque.objects.filter(origem="retorno_os").exists())

    def test_retirada_util_devolve_ao_estoque_sem_fornecedor(self):
        ordem, _ = self.abrir()
        self.servico(ordem, [self.item(acao="retirar_reutilizar")])
        self.assertFalse(self.ativo.componentes_instalados.filter(componente=self.componentes["ram"]).exists())
        movimento = MovimentoEstoque.objects.get()
        self.assertEqual(movimento.origem, "retorno_os")
        self.assertIsNone(movimento.fornecedor_id)
        self.assertEqual(movimento.intervencao.registro_os.ordem_id, ordem.pk)
        self.assertEqual(componentes_com_saldo().get(pk=self.componentes["ram"].pk).saldo, 1)

    def test_reenvio_servico_e_retorno_idempotentes(self):
        ordem, _ = self.abrir()
        dados = {**self.dados(ordem), "descricao": "Retirada para reaproveitar.", "itens": [self.item(acao="retirar_reutilizar")]}
        registro, _ = registrar_servico(**dados)
        repetido, criado = registrar_servico(**dados)
        self.assertFalse(criado)
        self.assertEqual(registro.pk, repetido.pk)
        registrar_retorno_intervencao(intervencao=registro.intervencoes.get(), usuario=self.usuario)
        self.assertEqual(MovimentoEstoque.objects.count(), 1)
        with self.assertRaisesMessage(ValidationError, "outros dados"):
            registrar_servico(**{**dados, "descricao": "Texto diferente"})

    def test_falta_de_estoque_reverte_inclusive_primeiro_retorno(self):
        ordem, _ = self.abrir()
        with self.assertRaisesMessage(ValidationError, "Estoque insuficiente"):
            self.servico(ordem, [self.item(acao="retirar_reutilizar"), self.item("fonte")])
        self.assertFalse(MovimentoEstoque.objects.exists())
        self.assertFalse(Registro.objects.exists())
        self.assertEqual(self.ativo.componentes_instalados.get(componente=self.componentes["ram"]).quantidade, 1)
        self.assertEqual(IntervencaoComponente.objects.count(), 5)

    def test_nao_retira_mais_do_que_instalado_inclusive_linhas_divididas(self):
        ordem, _ = self.abrir()
        with self.assertRaisesMessage(ValidationError, "quantidade instalada"):
            self.servico(ordem, [self.item(acao="retirar_reutilizar"), self.item(acao="retirar_sem_retorno")])
        self.assertFalse(Registro.objects.exists())

    def test_quantidade_invalida_e_componentes_inexistentes_rejeitados(self):
        ordem, _ = self.abrir()
        for item in (self.item(quantidade=0), self.item(quantidade=True), {**self.item(), "componente_id": 999999}):
            with self.subTest(item=item), self.assertRaises(ValidationError):
                self.servico(ordem, [item])

    def test_versao_antiga_nao_sobrescreve_outro_tecnico(self):
        ordem, _ = self.abrir()
        dados = self.dados(ordem)
        self.servico(ordem)
        with self.assertRaisesMessage(ValidationError, "alterada por outro"):
            concluir_os(**dados, resultado="reparado", descricao="Concluído.")
        self.assertEqual(Registro.objects.count(), 1)

    def test_conclusao_reparado_exige_composicao_completa(self):
        ordem, _ = self.abrir()
        self.servico(ordem, [self.item(acao="retirar_sem_retorno")])
        with self.assertRaisesMessage(ValidationError, "configuração deve estar completa"):
            self.concluir(ordem)
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, "em_atendimento")
        self.assertIsNone(ordem.concluido_em)

    def test_devolucao_exige_conclusao_e_recebedor(self):
        ordem, _ = self.abrir()
        with self.assertRaisesMessage(ValidationError, "Conclua"):
            self.encerrar(ordem)
        self.concluir(ordem)
        with self.assertRaises(ValidationError):
            encerrar_os(**self.dados(ordem), recebido_por=" ", para_baixa=False)
        ordem.refresh_from_db()
        self.assertEqual(ordem.status, "aguardando_coleta")

    def test_devolucao_reparado_restaura_reserva_e_admite_outro_nome(self):
        Ativo.objects.filter(pk=self.ativo.pk).update(situacao="reserva")
        ordem, _ = self.abrir()
        self.concluir(ordem)
        self.ativo.refresh_from_db()
        self.assertEqual(self.ativo.situacao, "em_manutencao")
        self.encerrar(ordem)
        ordem.refresh_from_db()
        self.ativo.refresh_from_db()
        self.assertEqual(self.ativo.situacao, "reserva")
        self.assertEqual(ordem.recebido_por, "Motorista B")
        self.assertEqual(ordem.status, "encerrada")
        nova, _ = self.abrir()
        self.assertNotEqual(nova.pk, ordem.pk)

    def test_sem_reparo_pode_ser_devolvido_sem_virar_em_uso(self):
        ordem, _ = self.abrir()
        self.concluir(ordem, "sem_reparo")
        self.encerrar(ordem)
        self.ativo.refresh_from_db()
        self.assertEqual(self.ativo.situacao, "sem_reparo")

    def test_encerrar_para_baixa_nao_da_baixa_nem_retorna_pecas(self):
        ordem, _ = self.abrir()
        self.concluir(ordem, "sem_reparo")
        registro, _ = self.encerrar(ordem, True)
        ordem.refresh_from_db()
        self.ativo.refresh_from_db()
        self.assertEqual(registro.tipo, "para_baixa")
        self.assertTrue(ordem.encerrada_para_baixa)
        self.assertEqual(ordem.recebido_por, "")
        self.assertEqual(self.ativo.situacao, "sem_reparo")
        self.assertEqual(self.ativo.componentes_instalados.count(), 5)
        self.assertFalse(MovimentoEstoque.objects.exists())

    def test_reparado_nao_encerra_para_baixa(self):
        ordem, _ = self.abrir()
        self.concluir(ordem)
        with self.assertRaisesMessage(ValidationError, "exige resultado Sem reparo"):
            self.encerrar(ordem, True)

    def test_fechado_nao_admite_servicos_e_estado_ilegal_e_bloqueado_no_banco(self):
        ordem, _ = self.abrir()
        with self.assertRaises(IntegrityError), transaction.atomic():
            OS.objects.filter(pk=ordem.pk).update(status="encerrada")
        self.concluir(ordem)
        self.encerrar(ordem)
        with self.assertRaisesMessage(ValidationError, "após a conclusão"):
            self.servico(ordem)
        with self.assertRaises(ValidationError):
            ordem.registros.first().delete()

    def test_consulta_filtra_ativo_data_e_tecnico_de_servico(self):
        ordem, _ = self.abrir()
        outro = get_user_model().objects.create_user(username="outro_tecnico")
        self.servico(ordem, usuario=outro)
        dados = {"q": self.ativo.dti, "inicio": timezone.localdate(), "fim": timezone.localdate(), "tecnico": outro, "status": "abertas"}
        self.assertEqual(list(filtrar_ordens(ordens_para_consulta(), dados)), [ordem])

    def test_busca_livre_encontra_serie_mas_nao_data_de_abertura(self):
        Ativo.objects.filter(pk=self.ativo.pk).update(numero_serie="SERIE-987654")
        ordem, _ = self.abrir()
        OS.objects.filter(pk=ordem.pk).update(aberto_em=timezone.now().replace(year=1998))
        self.assertEqual(list(filtrar_ordens(ordens_para_consulta(), {"q": "987654"})), [ordem])
        self.assertFalse(filtrar_ordens(ordens_para_consulta(), {"q": "1998"}).exists())

    def test_busca_os_por_departamento_nome_sigla_e_nome_historico(self):
        ordem, _ = self.abrir()
        for termo in ("saúde", "SMS"):
            self.assertEqual(list(filtrar_ordens(ordens_para_consulta(), {"q": termo})), [ordem])
        salvar_departamento(departamento_id=self.departamento.pk, nome="Vigilância Sanitária", sigla="VISA")
        for termo in ("Saúde", "Vigilância", "visa"):
            with self.subTest(termo=termo):
                self.assertEqual(list(filtrar_ordens(ordens_para_consulta(), {"q": termo})), [ordem])
        ordem.refresh_from_db()
        self.assertEqual(ordem.nome_departamento, "Saúde")

    def test_departamento_na_busca_respeita_demais_filtros_e_relatorio(self):
        ordem, _ = self.abrir()
        self.client.force_login(self.usuario)
        resposta = self.client.get(reverse("ordens:listar"), {"q": "SMS", "status": "abertas"})
        self.assertEqual(list(resposta.context["page_obj"]), [ordem])
        resposta = self.client.get(reverse("ordens:listar"), {"q": "SMS", "status": "encerrada"})
        self.assertEqual(list(resposta.context["page_obj"]), [])
        resposta = self.client.get(reverse("relatorios:consultar", args=["ordens"]), {"q": "SMS"})
        self.assertEqual(resposta.context["page_obj"].paginator.count, 1)

    def test_pdf_aberto_e_encerrado_preserva_identificacao_sem_mutacao(self):
        ordem, _ = self.abrir(problema="Falha <fonte> & diagnóstico.\nNão liga.")
        original = gerar_pdf_os(ordem)
        self.assertTrue(original.startswith(b"%PDF-"))
        self.assertGreater(len(original), 10000)
        Ativo.objects.filter(pk=self.ativo.pk).update(dti="NOVO-0010")
        self.assertEqual(ordem.dti_ativo, "OS-0010")
        self.assertEqual(list(filtrar_ordens(ordens_para_consulta(), {"q": "NOVO-0010"})), [ordem])
        self.concluir(ordem)
        self.encerrar(ordem)
        ordem.refresh_from_db()
        self.assertTrue(gerar_pdf_os(ordem).startswith(b"%PDF-"))
        self.assertEqual(Registro.objects.count(), 2)

    def test_acesso_protegido_post_csrf_e_pdf_sem_cache(self):
        ordem, _ = self.abrir()
        for nome, args in (("listar", []), ("selecionar_ativo", []), ("abrir", [self.ativo.pk]), ("detalhar", [ordem.pk]), ("imprimir", [ordem.pk]), ("operar", [ordem.pk, "servico"])):
            with self.subTest(nome=nome):
                self.assertEqual(self.client.get(reverse(f"ordens:{nome}", args=args)).status_code, 302)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuario)
        self.assertEqual(cliente.post(reverse("ordens:operar", args=[ordem.pk, "concluir"]), {}).status_code, 403)
        resposta = cliente.get(reverse("ordens:imprimir", args=[ordem.pk]))
        self.assertEqual(resposta["Content-Type"], "application/pdf")
        self.assertIn("no-store", resposta["Cache-Control"])
        self.assertEqual(OS.objects.get(pk=ordem.pk).status, "aberta")

    def test_http_abertura_servico_sem_pecas_conclusao_e_devolucao(self):
        self.client.force_login(self.usuario)
        resposta = self.client.post(reverse("ordens:abrir", args=[self.ativo.pk]), {"entregue_por": "Ana", "problema": "Falha no sistema", "chave_confirmacao": uuid.uuid4()})
        self.assertEqual(resposta.status_code, 302)
        ordem = OS.objects.get()
        dados = {"versao": ordem.versao, "chave_confirmacao": uuid.uuid4(), "descricao": "Sistema atualizado", "pecas-TOTAL_FORMS": "2", "pecas-INITIAL_FORMS": "0", "pecas-MAX_NUM_FORMS": "50", "pecas-0-acao": "instalar", "pecas-0-quantidade": "1", "pecas-1-acao": "instalar", "pecas-1-quantidade": "1"}
        self.assertEqual(self.client.post(reverse("ordens:operar", args=[ordem.pk, "servico"]), dados).status_code, 302)
        ordem.refresh_from_db()
        self.assertEqual(self.client.post(reverse("ordens:operar", args=[ordem.pk, "concluir"]), {"versao": ordem.versao, "chave_confirmacao": uuid.uuid4(), "resultado": "reparado", "descricao": "Funcionando"}).status_code, 302)
        ordem.refresh_from_db()
        self.assertEqual(self.client.post(reverse("ordens:operar", args=[ordem.pk, "devolver"]), {"versao": ordem.versao, "chave_confirmacao": uuid.uuid4(), "recebido_por": "Bruno"}).status_code, 302)
        ordem.refresh_from_db()
        self.assertEqual(ordem.recebido_por, "Bruno")

    def test_inicial_nao_mostra_intervencoes_da_os_e_entrada_nao_oferece_retorno_manual(self):
        ordem, _ = self.abrir()
        self.entrada("ram", 1)
        self.servico(ordem, [self.item()])
        self.client.force_login(self.usuario)
        resposta = self.client.get(reverse("ativos:ativo_detalhar", args=[self.ativo.pk]))
        self.assertEqual(len(resposta.context["intervencoes"]), 5)
        self.assertNotIn("retorno_os", dict(EntradaEstoqueForm().fields["origem"].choices))

    def test_opcoes_de_peca_nao_multiplicam_saldo_por_ativos_instalados(self):
        self.entrada("ram", 5)
        novo_ativo(self.usuario, self.categoria, self.departamento, self.componentes, dti="OS-0020")
        campo = PecaServicoForm(ativo_id=self.ativo.pk).fields["componente"]
        ram = campo.queryset.get(pk=self.componentes["ram"].pk)
        self.assertEqual(ram.saldo, 5)
        self.assertIn("estoque: 5", campo.label_from_instance(ram))

    def test_metadados_podem_ser_editados_com_componente_retirado_em_manutencao(self):
        ordem, _ = self.abrir()
        self.servico(ordem, [self.item(acao="retirar_sem_retorno")])
        self.ativo.refresh_from_db()
        dados = {campo: getattr(self.ativo, campo) for campo in CAMPOS_ATIVO}
        dados["observacoes"] = "Aguardando peça de reposição."
        editado = editar_ativo(ativo_id=self.ativo.pk, dados=dados, especificacoes={}, extras=[], versao=self.ativo.versao)
        self.assertEqual(editado.observacoes, dados["observacoes"])
        self.assertEqual(editado.situacao, "em_manutencao")


class ConcorrenciaOSTests(TransactionTestCase):
    def setUp(self):
        self.usuario, self.categoria, self.departamento, self.componentes = preparar()
        self.ativo = novo_ativo(self.usuario, self.categoria, self.departamento, self.componentes)

    def paralelo(self, funcao):
        barreira = Barrier(2)
        def executar(indice):
            close_old_connections()
            try:
                usuario = get_user_model().objects.get(pk=self.usuario.pk)
                barreira.wait(timeout=10)
                return funcao(indice, usuario)
            except ValidationError:
                return "rejeitado"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(executar, range(2)))

    def test_abertura_concorrente_gera_uma_unica_os(self):
        def abrir(indice, usuario):
            abrir_os(ativo_id=self.ativo.pk, entregue_por="Motorista", problema="Falha", usuario=usuario, chave_confirmacao=uuid.uuid4())
            return "criada"
        self.assertCountEqual(self.paralelo(abrir), ["criada", "rejeitado"])
        self.assertEqual(OS.objects.count(), 1)

    def test_duas_os_disputam_ultima_peca_sem_saldo_negativo(self):
        outro = novo_ativo(self.usuario, self.categoria, self.departamento, self.componentes, dti="OS-0020")
        ordens = [abrir_os(ativo_id=a.pk, entregue_por="Motorista", problema="Upgrade", usuario=self.usuario, chave_confirmacao=uuid.uuid4())[0] for a in (self.ativo, outro)]
        registrar_entrada(componente_id=self.componentes["ram"].pk, quantidade=1, origem="compra", data=timezone.localdate(), usuario=self.usuario, chave_confirmacao=uuid.uuid4())
        def consumir(indice, usuario):
            registrar_servico(ordem_id=ordens[indice].pk, descricao="Upgrade", itens=[{"componente_id": self.componentes["ram"].pk, "quantidade": 1, "acao": "instalar"}], usuario=usuario, chave_confirmacao=uuid.uuid4(), versao=1)
            return "confirmada"
        self.assertCountEqual(self.paralelo(consumir), ["confirmada", "rejeitado"])
        self.assertEqual(componentes_com_saldo().get(pk=self.componentes["ram"].pk).saldo, 0)
        self.assertEqual(Registro.objects.count(), 1)
        self.assertEqual(MovimentoEstoque.objects.filter(tipo="saida").count(), 1)

    def test_mesma_confirmacao_concorrente_nao_duplica_consumo(self):
        ordem = abrir_os(ativo_id=self.ativo.pk, entregue_por="Motorista", problema="Upgrade", usuario=self.usuario, chave_confirmacao=uuid.uuid4())[0]
        registrar_entrada(componente_id=self.componentes["ram"].pk, quantidade=2, origem="compra", data=timezone.localdate(), usuario=self.usuario, chave_confirmacao=uuid.uuid4())
        chave = uuid.uuid4()
        def consumir(indice, usuario):
            return registrar_servico(ordem_id=ordem.pk, descricao="Upgrade", itens=[{"componente_id": self.componentes["ram"].pk, "quantidade": 1, "acao": "instalar"}], usuario=usuario, chave_confirmacao=chave, versao=1)[1]
        self.assertCountEqual(self.paralelo(consumir), [True, False])
        self.assertEqual(componentes_com_saldo().get(pk=self.componentes["ram"].pk).saldo, 1)
        self.assertEqual(Registro.objects.count(), 1)
