from django.db.models import BigIntegerField, BooleanField, Case, F, Q, Sum, Value, When
from django.db.models.functions import Coalesce

from .models import Componente, MovimentoEstoque


def componentes_com_saldo():
    """Saldo derivado do histórico, compartilhado por listagem e detalhe."""
    return Componente.objects.annotate(
        saldo=Coalesce(Sum(Case(
            When(movimentos__tipo=MovimentoEstoque.Tipo.ENTRADA, then=F("movimentos__quantidade")),
            default=-F("movimentos__quantidade"), output_field=BigIntegerField(),
        )), Value(0), output_field=BigIntegerField()),
    ).annotate(estoque_baixo=Case(
        When(Q(ativo=True, acompanhar_estoque=True) & Q(saldo__lte=F("quantidade_minima")), then=Value(True)),
        default=Value(False), output_field=BooleanField(),
    )).order_by("chave_nome", "pk")
