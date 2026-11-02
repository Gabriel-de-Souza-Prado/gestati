import uuid

from django.test import TestCase
from django.urls import reverse

from cadastros.models import Departamento
from ordens.services import abrir_os
from relatorios.apresentacao import linha
from relatorios.selectors import consultar
from .services import cadastrar_ativo
from .tests_integracao import preparar_cadastros


class DepartamentoInativoTests(TestCase):
    def test_inativado_aparece_no_vinculo_atual_sem_reescrever_nome_historico(self):
        usuario,categoria,departamento,componentes=preparar_cadastros()
        ativo=cadastrar_ativo(dados={"dti":"INATIVO-0010","categoria_id":categoria.pk,"departamento_id":departamento.pk},
            itens=[{"componente_id":c.pk,"quantidade":1,"origem":"no_equipamento"} for c in componentes.values()],
            especificacoes={},extras=[],usuario=usuario,chave_confirmacao=uuid.uuid4())[0]
        os=abrir_os(ativo_id=ativo.pk,entregue_por="Pessoa A",problema="Teste",usuario=usuario,chave_confirmacao=uuid.uuid4())[0]
        departamento.ativo=False;departamento.save()
        self.assertEqual(Departamento.objects.get(pk=departamento.pk).nome,"Saúde")
        self.assertEqual(str(departamento),"Saúde (Inativado)")
        os.refresh_from_db();self.assertEqual(os.nome_departamento,"Saúde")
        self.client.force_login(usuario)
        for nome in ("ativo_listar","ativo_detalhar","ativo_editar"):
            url=reverse("ativos:"+nome,args=[ativo.pk] if nome!="ativo_listar" else [])
            self.assertContains(self.client.get(url),"Saúde (Inativado)")
        r=consultar("ativos",{}).get(pk=ativo.pk)
        self.assertEqual(linha("ativos",r)["celulas"][2],"Saúde (Inativado)")
