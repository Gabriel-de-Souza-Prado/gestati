from django.core.exceptions import ValidationError


def impedir_emprestimo_pendente(ativo):
    """A posse temporária precisa ser regularizada antes de novo uso físico."""
    if ativo.emprestimos.filter(encerrado_em__isnull=True).exists():
        raise ValidationError("Este ativo está emprestado. Registre a devolução antes de abrir OS ou alterar seus componentes. A transferência definitiva pode encerrar o empréstimo.")
