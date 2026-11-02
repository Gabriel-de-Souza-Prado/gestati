from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from ativos.alteracoes import alterar_configuracao
from ativos.models import Ativo, IntervencaoComponente
from ativos.services import cadastrar_ativo
from ativos.tests_integracao import preparar_cadastros
from cadastros.services import salvar_departamento
from estoque.models import Componente, MovimentoEstoque
from estoque.selectors import componentes_com_saldo
from estoque.services import registrar_entrada
from movimentacoes.services import devolver_emprestimo, emprestar_ativo, transferir_ativo
from ordens.services import abrir_os, concluir_os, encerrar_os, registrar_servico
from .models import BaixaAtivo
from .pdf import gerar_pdf_baixa
from .services import baixar_ativo


def preparar():
    u, categoria, departamento, componentes = preparar_cadastros()
    ativo, _ = cadastrar_ativo(dados={"dti": "BXA-0010", "patrimonio": "PAT-0010", "modelo": "Computador teste",
        "categoria_id": categoria.pk, "departamento_id": departamento.pk},
        itens=[{"componente_id": c.pk, "quantidade": 2 if c.tipo == "ram" else 1, "origem": "no_equipamento"} for c in componentes.values()],
        especificacoes={"hostname": "PC-RH-TESTE", "sistema_operacional": "Windows 11"}, extras=[], usuario=u, chave_confirmacao=uuid.uuid4())
    return u, departamento, componentes, ativo


class BaixasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario, cls.departamento, cls.componentes, cls.ativo = preparar()

    def dados(self, **alteracoes):
        self.ativo.refresh_from_db()
        return {"ativo_id": self.ativo.pk, "motivo": "Placa-mãe sem reparo; recuperar peças úteis.",
                "itens": [{"componente_id": self.componentes["ram"].pk, "quantidade": 1},
                          {"componente_id": self.componentes["ssd"].pk, "quantidade": 1}],
                "usuario": self.usuario, "versao": self.ativo.versao, "chave_confirmacao": uuid.uuid4(), **alteracoes}

    def confirmar(self, **alteracoes):
        dados = self.dados(**alteracoes)
        previa, _ = baixar_ativo(**dados)
        return baixar_ativo(**dados, previa=previa)[0]

    def abrir(self):
        return abrir_os(ativo_id=self.ativo.pk, problema="Não liga", entregue_por="Pessoa A",
                        usuario=self.usuario, chave_confirmacao=uuid.uuid4())[0]

    def encerrar_para_baixa(self):
        ordem = self.abrir()
        concluir_os(ordem_id=ordem.pk, resultado="sem_reparo", descricao="Placa-mãe sem reparo.", usuario=self.usuario,
                    chave_confirmacao=uuid.uuid4(), versao=ordem.versao)
        ordem.refresh_from_db()
        encerrar_os(ordem_id=ordem.pk, recebido_por="", para_baixa=True, usuario=self.usuario,
                    chave_confirmacao=uuid.uuid4(), versao=ordem.versao)
        return ordem

    def test_previa_nao_grava_baixa_movimentos_ou_retiradas(self):
        previa, criado = baixar_ativo(**self.dados())
        self.assertFalse(criado)
        self.assertEqual(previa["recuperados"][0]["saldo_depois"], 1)
        self.assertFalse(BaixaAtivo.objects.exists())
        self.assertFalse(MovimentoEstoque.objects.exists())
        self.assertEqual(self.ativo.componentes_instalados.get(componente=self.componentes["ram"]).quantidade, 2)

    def test_baixa_recupera_somente_selecionados_com_origem_e_sem_fornecedor(self):
        Componente.objects.filter(pk=self.componentes["ram"].pk).update(acompanhar_estoque=False)
        registro = self.confirmar()
        self.ativo.refresh_from_db()
        self.assertEqual(self.ativo.situacao, "baixado")
        self.assertEqual(self.ativo.departamento_id, self.departamento.pk)
        self.assertEqual(self.ativo.especificacoes["sistema_operacional"], "Windows 11")
        self.assertEqual(registro.configuracao_anterior[2]["quantidade"], 2)
        self.assertEqual(registro.intervencoes.count(), 2)
        self.assertEqual(MovimentoEstoque.objects.count(), 2)
        self.assertFalse(MovimentoEstoque.objects.exclude(origem="recuperacao_baixa", tipo="entrada", fornecedor__isnull=True).exists())
        self.assertEqual(self.ativo.componentes_instalados.get(componente=self.componentes["ram"]).quantidade, 1)
        self.assertFalse(self.ativo.componentes_instalados.filter(componente=self.componentes["ssd"]).exists())
        self.assertTrue(self.ativo.componentes_instalados.filter(componente=self.componentes["placa_mae"]).exists())
        self.assertTrue(Componente.objects.get(pk=self.componentes["ram"].pk).acompanhar_estoque)
        self.assertEqual(componentes_com_saldo().get(pk=self.componentes["ram"].pk).saldo, 1)

    def test_baixa_direta_sem_recuperacao_nao_exige_os_nem_gera_entrada(self):
        registro = self.confirmar(itens=[])
        self.assertIsNone(registro.ordem_id)
        self.assertEqual(registro.configuracao_anterior, registro.configuracao_remanescente)
        self.assertFalse(MovimentoEstoque.objects.exists())

    def test_todas_as_pecas_podem_ser_recuperadas_sem_exigir_composicao_completa(self):
        itens = [{"componente_id": l.componente_id, "quantidade": l.quantidade} for l in self.ativo.componentes_instalados.all()]
        self.confirmar(itens=itens)
        self.assertFalse(self.ativo.componentes_instalados.exists())
        self.assertEqual(MovimentoEstoque.objects.count(), 5)

    def test_os_para_baixa_mantem_pendencia_ate_confirmacao_propria(self):
        ordem = self.encerrar_para_baixa()
        self.ativo.refresh_from_db()
        self.assertEqual(self.ativo.situacao, "sem_reparo")
        self.assertFalse(BaixaAtivo.objects.exists())
        self.client.force_login(self.usuario)
        resposta = self.client.get(reverse("baixas:registrar", args=[self.ativo.pk]))
        self.assertEqual(resposta.context["ordem"].pk, ordem.pk)
        registro = self.confirmar(ordem_id=ordem.pk)
        self.assertEqual(registro.ordem_id, ordem.pk)
        self.assertEqual(registro.situacao_anterior, "sem_reparo")
        resposta = self.client.get(reverse("ordens:detalhar", args=[ordem.pk]))
        self.assertContains(resposta, "A baixa foi confirmada separadamente")

    def test_os_aberta_inclusive_aguardando_coleta_impede_baixa(self):
        ordem = self.abrir()
        with self.assertRaisesMessage(ValidationError, "Encerre a OS"):
            baixar_ativo(**self.dados())
        concluir_os(ordem_id=ordem.pk, resultado="sem_reparo", descricao="Sem reparo", usuario=self.usuario,
                    chave_confirmacao=uuid.uuid4(), versao=ordem.versao)
        with self.assertRaisesMessage(ValidationError, "Encerre a OS"):
            baixar_ativo(**self.dados())

    def emprestar(self):
        destino = salvar_departamento(nome="RH")
        return emprestar_ativo(ativo_id=self.ativo.pk, destino_id=destino.pk, motivo="Substituição", recebido_por="Pessoa B",
                        usuario=self.usuario, chave_confirmacao=uuid.uuid4(), versao=self.ativo.versao)

    def test_baixa_encerra_emprestimo_automaticamente_sem_devolucao_ficticia(self):
        emprestimo, _ = self.emprestar()
        registro = self.confirmar()
        emprestimo.refresh_from_db()
        self.assertEqual(emprestimo.encerramento, "baixa")
        self.assertEqual(emprestimo.baixa_definitiva_id, registro.pk)
        self.assertEqual(emprestimo.encerrado_em, registro.registrado_em)
        self.assertIsNone(emprestimo.devolvido_em)
        self.assertEqual(emprestimo.devolvido_por, "")
        self.assertIsNone(emprestimo.recebido_devolucao_por_id)
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("movimentacoes:detalhar", args=["emprestimos", emprestimo.pk]))
        self.assertContains(r, "Encerrado automaticamente por baixa")
        self.assertContains(r, reverse("baixas:detalhar", args=[registro.pk]))
        filtrado = self.client.get(reverse("movimentacoes:listar"), {"tipo": "emprestimos", "situacao": "baixados"})
        self.assertEqual(list(filtrado.context["page_obj"]), [emprestimo])
        with self.assertRaisesMessage(ValidationError, "já foi encerrado"):
            devolver_emprestimo(emprestimo_id=emprestimo.pk, devolvido_por="Pessoa C", usuario=self.usuario,
                               chave_confirmacao=uuid.uuid4(), versao=3)

    def test_previa_mostra_fechamento_e_reenvio_nao_encerra_emprestimo_de_novo(self):
        emprestimo, _ = self.emprestar()
        dados = self.dados()
        previa, _ = baixar_ativo(**dados)
        self.assertEqual(previa["emprestimo"]["id"], emprestimo.pk)
        emprestimo.refresh_from_db()
        self.assertIsNone(emprestimo.encerrado_em)
        registro, _ = baixar_ativo(**dados, previa=previa)
        repetido, criado = baixar_ativo(**dados, previa=previa)
        self.assertFalse(criado)
        self.assertEqual(repetido.pk, registro.pk)
        self.assertEqual(MovimentoEstoque.objects.count(), 2)

    def test_falha_na_baixa_mantem_emprestimo_aberto(self):
        emprestimo, _ = self.emprestar()
        dados = self.dados()
        previa, _ = baixar_ativo(**dados)
        with patch("ativos.intervencoes.registrar_retorno_intervencao", side_effect=ValidationError("Falha simulada")), self.assertRaises(ValidationError):
            baixar_ativo(**dados, previa=previa)
        emprestimo.refresh_from_db()
        self.assertIsNone(emprestimo.encerrado_em)
        self.assertIsNone(emprestimo.baixa_definitiva_id)
        self.assertFalse(BaixaAtivo.objects.exists())

    def test_reenvio_nao_duplica_e_payload_alterado_rejeitado(self):
        dados = self.dados()
        previa, _ = baixar_ativo(**dados)
        um, _ = baixar_ativo(**dados, previa=previa)
        dois, criado = baixar_ativo(**dados, previa=previa)
        self.assertEqual(um.pk, dois.pk)
        self.assertFalse(criado)
        self.assertEqual(MovimentoEstoque.objects.count(), 2)
        with self.assertRaisesMessage(ValidationError, "outros dados"):
            baixar_ativo(**{**dados, "motivo": "Outro motivo"}, previa=previa)

    def test_baixa_nova_de_ativo_ja_baixado_rejeitada(self):
        self.confirmar()
        with self.assertRaisesMessage(ValidationError, "já foi baixado"):
            baixar_ativo(**self.dados())

    def test_motivo_quantidade_peca_estranha_e_inativa_rejeitados(self):
        ram = self.componentes["ram"].pk
        for mudanca in ({"motivo": " "}, {"itens": [{"componente_id": ram, "quantidade": 3}]},
                        {"itens": [{"componente_id": ram, "quantidade": -1}]},
                        {"itens": [{"componente_id": ram, "quantidade": True}]},
                        {"itens": [{"componente_id": 999999, "quantidade": 1}]},
                        {"itens": [{"componente_id": ram, "quantidade": 1}] * 2}):
            with self.subTest(mudanca=mudanca), self.assertRaises(ValidationError):
                baixar_ativo(**self.dados(**mudanca))
        Componente.objects.filter(pk=ram).update(ativo=False)
        with self.assertRaisesMessage(ValidationError, "Reative"):
            baixar_ativo(**self.dados())
        self.assertFalse(BaixaAtivo.objects.exists())

    def test_versao_antiga_e_saldo_alterado_exigem_nova_previa(self):
        dados = self.dados()
        previa, _ = baixar_ativo(**dados)
        registrar_entrada(componente_id=self.componentes["ram"].pk, quantidade=5, origem="compra", data=timezone.localdate(),
                         usuario=self.usuario, chave_confirmacao=uuid.uuid4())
        with self.assertRaisesMessage(ValidationError, "saldos mudaram"):
            baixar_ativo(**dados, previa=previa)
        Ativo.objects.filter(pk=self.ativo.pk).update(versao=2)
        with self.assertRaisesMessage(ValidationError, "ativo mudou"):
            baixar_ativo(**dados)
        self.assertFalse(BaixaAtivo.objects.exists())

    def test_falha_na_entrada_reverte_baixa_composicao_e_entradas_anteriores(self):
        dados = self.dados()
        previa, _ = baixar_ativo(**dados)
        from ativos.intervencoes import registrar_retorno_intervencao as real
        contador = []
        def falhar(**kw):
            contador.append(1)
            if len(contador) == 2:
                raise ValidationError("Falha simulada no segundo recebimento")
            return real(**kw)
        with patch("ativos.intervencoes.registrar_retorno_intervencao", side_effect=falhar), self.assertRaises(ValidationError):
            baixar_ativo(**dados, previa=previa)
        self.ativo.refresh_from_db()
        self.assertEqual(self.ativo.situacao, "em_uso")
        self.assertEqual(self.ativo.componentes_instalados.count(), 5)
        self.assertFalse(BaixaAtivo.objects.exists())
        self.assertFalse(MovimentoEstoque.objects.exists())

    def test_baixado_bloqueia_os_emprestimo_transferencia_e_pecas(self):
        self.confirmar()
        destino = salvar_departamento(nome="RH")
        with self.assertRaises(ValidationError):
            self.abrir()
        for func in (emprestar_ativo, transferir_ativo):
            with self.assertRaises(ValidationError):
                func(ativo_id=self.ativo.pk, destino_id=destino.pk, motivo="Teste", usuario=self.usuario,
                     chave_confirmacao=uuid.uuid4(), versao=2, **({"recebido_por": "Pessoa B"} if func is emprestar_ativo else {}))
        with self.assertRaises(ValidationError):
            alterar_configuracao(ativo_id=self.ativo.pk, tipo="fisica", justificativa="Teste", usuario=self.usuario,
                chave_confirmacao=uuid.uuid4(), versao=2, itens=[{"componente_id": self.componentes["ram"].pk, "acao": "retirar_reutilizar", "quantidade": 1}])

    def test_documento_preserva_nomes_e_bloqueia_exclusao_do_historico(self):
        registro = self.confirmar()
        antigo = registro.nome_departamento
        self.departamento.nome = "Nome alterado"
        self.departamento.save()
        registro.refresh_from_db()
        self.assertEqual(registro.nome_departamento, antigo)
        with self.assertRaises(ValidationError): registro.save()
        with self.assertRaises(ValidationError): registro.delete()
        with self.assertRaises(ProtectedError): self.ativo.delete()

    def test_vinculo_de_intervencao_nao_pode_ser_baixa_e_os_ao_mesmo_tempo(self):
        ordem = self.encerrar_para_baixa()
        registro = self.confirmar(ordem_id=ordem.pk)
        evento = registro.intervencoes.first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            IntervencaoComponente.objects.filter(pk=evento.pk).update(registro_os_id=ordem.registros.first().pk)

    def test_pdf_e_consulta_autenticados_get_nao_movimentam_estoque(self):
        registro = self.confirmar()
        urls = [reverse("baixas:listar"), reverse("baixas:selecionar"), reverse("baixas:registrar", args=[self.ativo.pk]),
                reverse("baixas:detalhar", args=[registro.pk]), reverse("baixas:imprimir", args=[registro.pk])]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.usuario)
        for url in urls:
            self.assertIn(self.client.get(url).status_code, (200, 302))
        r = self.client.get(urls[-1])
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn("no-store", r["Cache-Control"])
        self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertEqual(self.client.post(urls[-1]).status_code, 405)
        self.assertEqual(MovimentoEstoque.objects.count(), 2)
        ficha = self.client.get(reverse("ativos:ativo_detalhar", args=[self.ativo.pk]))
        self.assertContains(ficha, "Equipamento baixado")
        self.assertNotContains(ficha, "Alterar configuração</a>")

    def test_confirmacao_assinada_csrf_reenvio_e_troca_de_usuario(self):
        self.client.force_login(self.usuario)
        url = reverse("baixas:registrar", args=[self.ativo.pk])
        entrada = {"motivo": "Obsolescência", "versao": 1, "chave_confirmacao": str(uuid.uuid4()),
                   f"recuperar_{self.componentes['ram'].pk}": 1}
        r = self.client.post(url, entrada)
        token = r.context["token"]
        self.assertFalse(BaixaAtivo.objects.exists())
        protegido = Client(enforce_csrf_checks=True)
        protegido.force_login(self.usuario)
        self.assertEqual(protegido.post(url, {"confirmacao": token}).status_code, 403)
        outro = get_user_model().objects.create_user(username="outro_ti")
        self.client.force_login(outro)
        self.assertContains(self.client.post(url, {"confirmacao": token}), "inválida")
        self.assertFalse(BaixaAtivo.objects.exists())
        self.client.force_login(self.usuario)
        self.assertEqual(self.client.post(url, {"confirmacao": token}).status_code, 302)
        self.assertEqual(self.client.post(url, {"confirmacao": token}).status_code, 302)
        self.assertEqual(BaixaAtivo.objects.count(), 1)
        self.assertEqual(MovimentoEstoque.objects.count(), 1)

    def test_filtros_buscam_hostname_identificadores_e_periodo(self):
        registro = self.confirmar()
        self.client.force_login(self.usuario)
        for q in ("RH", "BXA-0010", "PAT-0010", "Computador teste"):
            r = self.client.get(reverse("baixas:listar"), {"q": q, "inicio": timezone.localdate().isoformat()})
            self.assertEqual(list(r.context["page_obj"]), [registro])
        r = self.client.get(reverse("baixas:listar"), {"inicio": "2026-12-31", "fim": "2026-01-01"})
        self.assertEqual(len(r.context["page_obj"]), 0)

    def test_pdf_sem_patrimonio_e_textos_longos(self):
        registro = self.confirmar(itens=[])
        registro.patrimonio_ativo = ""
        registro.motivo = ("Manutenção impossível <avaliação> & recuperação. " * 70)[:3000]
        self.assertTrue(gerar_pdf_baixa(registro).startswith(b"%PDF"))

    def test_retorno_na_os_reduz_quantidade_disponivel_para_recuperar_na_baixa(self):
        ordem=self.abrir()
        ram=self.componentes["ram"]
        registrar_servico(ordem_id=ordem.pk,descricao="Uma RAM útil retirada",itens=[{"componente_id":ram.pk,"acao":"retirar_reutilizar","quantidade":1}],usuario=self.usuario,chave_confirmacao=uuid.uuid4(),versao=1)
        ordem.refresh_from_db()
        concluir_os(ordem_id=ordem.pk,resultado="sem_reparo",descricao="Placa-mãe sem reparo",usuario=self.usuario,chave_confirmacao=uuid.uuid4(),versao=ordem.versao)
        ordem.refresh_from_db()
        encerrar_os(ordem_id=ordem.pk,recebido_por="",para_baixa=True,usuario=self.usuario,chave_confirmacao=uuid.uuid4(),versao=ordem.versao)
        with self.assertRaisesMessage(ValidationError,"quantidades instalados"):
            baixar_ativo(**self.dados(ordem_id=ordem.pk,itens=[{"componente_id":ram.pk,"quantidade":2}]))
        self.confirmar(ordem_id=ordem.pk,itens=[{"componente_id":ram.pk,"quantidade":1}])
        self.assertEqual(componentes_com_saldo().get(pk=ram.pk).saldo,2)
        self.assertEqual(MovimentoEstoque.objects.filter(componente=ram).count(),2)

    def test_entrada_manual_nao_pode_inventar_recuperacao_sem_baixa(self):
        with self.assertRaises(ValidationError):
            registrar_entrada(componente_id=self.componentes["ram"].pk, quantidade=1, origem="recuperacao_baixa",
                             data=timezone.localdate(), usuario=self.usuario, chave_confirmacao=uuid.uuid4())
        self.assertFalse(MovimentoEstoque.objects.exists())

    def test_os_invalida_e_usuario_inativo_rejeitados(self):
        with self.assertRaisesMessage(ValidationError, "OS de origem"):
            baixar_ativo(**self.dados(ordem_id=999999))
        self.usuario.is_active = False
        with self.assertRaisesMessage(ValidationError, "usuário ativo"):
            baixar_ativo(**self.dados())
        self.assertFalse(BaixaAtivo.objects.exists())


class ConcorrenciaBaixasTests(TransactionTestCase):
    def corrida(self, modo):
        u, depto, componentes, ativo = preparar()
        itens = [{"componente_id": componentes["ram"].pk, "quantidade": 1}]
        dados = {"ativo_id": ativo.pk, "motivo": "Sem reparo", "itens": itens, "usuario": u,
                 "chave_confirmacao": uuid.uuid4(), "versao": 1}
        previa, _ = baixar_ativo(**dados)
        destino = salvar_departamento(nome="Destino temporário") if modo == "emprestimo" else None
        barreira = Barrier(2)
        def executar(i):
            close_old_connections()
            try:
                usuario = get_user_model().objects.get(pk=u.pk)
                barreira.wait(timeout=10)
                if modo == "os" and i:
                    abrir_os(ativo_id=ativo.pk, problema="Não liga", entregue_por="Pessoa A", usuario=usuario, chave_confirmacao=uuid.uuid4())
                    return "os"
                if modo == "emprestimo" and i:
                    emprestar_ativo(ativo_id=ativo.pk, destino_id=destino.pk, motivo="Necessidade temporária", recebido_por="Pessoa B",
                                    usuario=usuario, chave_confirmacao=uuid.uuid4(), versao=1)
                    return "emprestimo"
                d = {**dados, "usuario": usuario}
                if modo == "diferentes": d["chave_confirmacao"] = uuid.uuid4()
                return "criado" if baixar_ativo(**d, previa=previa)[1] else "reenvio"
            except ValidationError:
                return "rejeitado"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(executar, range(2)))
        return resultados, ativo

    def test_mesma_confirmacao_concorrente_recupera_uma_vez(self):
        r, _ = self.corrida("iguais")
        self.assertCountEqual(r, ["criado", "reenvio"])
        self.assertEqual(MovimentoEstoque.objects.count(), 1)

    def test_baixas_distintas_concorrentes_nao_recuperam_duas_vezes(self):
        r, _ = self.corrida("diferentes")
        self.assertCountEqual(r, ["criado", "rejeitado"])
        self.assertEqual(BaixaAtivo.objects.count(), 1)
        self.assertEqual(MovimentoEstoque.objects.count(), 1)

    def test_baixa_contra_nova_os_nao_deixa_os_aberta_em_baixado(self):
        r, ativo = self.corrida("os")
        ativo.refresh_from_db()
        self.assertIn("rejeitado", r)
        if ativo.situacao == "baixado":
            self.assertFalse(ativo.ordens_servico.exists())
        else:
            self.assertEqual(ativo.ordens_servico.count(), 1)
            self.assertFalse(BaixaAtivo.objects.exists())

    def test_baixa_contra_emprestimo_serializa_indisponibilidade(self):
        r, ativo = self.corrida("emprestimo")
        ativo.refresh_from_db()
        self.assertIn("rejeitado", r)
        self.assertFalse(ativo.situacao == "baixado" and ativo.emprestimos.filter(encerrado_em__isnull=True).exists())

    def test_baixa_e_devolucao_simultaneas_so_encerram_emprestimo_uma_vez(self):
        u, depto, componentes, ativo = preparar()
        destino = salvar_departamento(nome="RH")
        emprestimo, _ = emprestar_ativo(ativo_id=ativo.pk, destino_id=destino.pk, motivo="Substituição", recebido_por="Pessoa A",
                                       usuario=u, chave_confirmacao=uuid.uuid4(), versao=1)
        dados = {"ativo_id": ativo.pk, "motivo": "Sem reparo", "itens": [], "usuario": u,
                 "chave_confirmacao": uuid.uuid4(), "versao": 2}
        previa, _ = baixar_ativo(**dados)
        barreira = Barrier(2)
        def executar(i):
            close_old_connections()
            try:
                usuario = get_user_model().objects.get(pk=u.pk)
                barreira.wait(timeout=10)
                if i:
                    devolver_emprestimo(emprestimo_id=emprestimo.pk, devolvido_por="Pessoa B", usuario=usuario,
                                       chave_confirmacao=uuid.uuid4(), versao=2)
                else:
                    baixar_ativo(**{**dados, "usuario": usuario}, previa=previa)
                return "confirmado"
            except ValidationError:
                return "rejeitado"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = list(pool.map(executar, range(2)))
        self.assertCountEqual(resultados, ["confirmado", "rejeitado"])
        emprestimo.refresh_from_db()
        self.assertIn(emprestimo.encerramento, ["baixa", "devolucao"])
        self.assertEqual(bool(emprestimo.baixa_definitiva_id), emprestimo.encerramento == "baixa")
