"""Documento de baixa a partir do evento preservado; imprimir não movimenta estoque."""
from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import CondPageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.pdf import LOCK_GERACAO_PDF


def gerar_pdf_baixa(registro):
    with LOCK_GERACAO_PDF:
        buffer = BytesIO()
        largura = A4[0] - 36*mm
        instante = timezone.localtime(registro.registrado_em).strftime("%d/%m/%Y %H:%M")
        emitido = timezone.localtime().strftime("%d/%m/%Y %H:%M")
        ink = colors.HexColor("#203642")
        corpo = ParagraphStyle("BaixaCorpo", fontName="Gestati", fontSize=10, leading=15, spaceAfter=8, textColor=ink)
        pequeno = ParagraphStyle("BaixaPequeno", parent=corpo, fontSize=8, leading=12)
        titulo = ParagraphStyle("BaixaTitulo", parent=corpo, fontName="GestatiBold", fontSize=21, leading=27, spaceAfter=14)
        secao = ParagraphStyle("BaixaSecao", parent=corpo, fontName="GestatiBold", fontSize=12, leading=17,
                               textColor=colors.HexColor("#08796E"), spaceBefore=12)

        def p(texto, estilo=corpo):
            return Paragraph(escape(str(texto or "Não informado")).replace("\n", "<br/>"), estilo)

        def campo(rotulo, valor):
            return Paragraph(f"<b>{escape(rotulo)}</b><br/>{escape(str(valor or 'Não informado'))}", corpo)

        def tabela(linhas, larguras, cabecalho=False):
            t = Table(linhas, colWidths=larguras, hAlign="LEFT", repeatRows=1 if cabecalho else 0)
            t.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#F1F6F5")),
                ("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 10),
                ("RIGHTPADDING", (0,0), (-1,-1), 10), ("TOPPADDING", (0,0), (-1,-1), 8),
                ("BOTTOMPADDING", (0,0), (-1,-1), 5)]))
            return t

        conteudo = [p("GESTATI | Gestão de itens de TI", pequeno), p("Baixa de equipamento", titulo),
                    p(f"Registro {registro.pk} | {instante}", pequeno)]
        conteudo += [tabela([
            [campo("EQUIPAMENTO", registro.descricao_ativo), campo("DTI", registro.dti_ativo)],
            [campo("PATRIMÔNIO", registro.patrimonio_ativo), campo("NÚMERO DE SÉRIE", registro.serie_ativo)],
            [campo("DEPARTAMENTO DE VÍNCULO", registro.nome_departamento), campo("SITUAÇÃO ANTERIOR", registro.get_situacao_anterior_display())],
            [campo("TÉCNICO RESPONSÁVEL", registro.nome_tecnico), campo("OS DE ORIGEM", f"OS {registro.ordem_id}" if registro.ordem_id else "Baixa direta, sem OS")],
        ], [largura*.56, largura*.44]), CondPageBreak(70), p("Motivo da baixa", secao), p(registro.motivo),
            CondPageBreak(90), p("Componentes recuperados para o estoque", secao)]
        if registro.recuperados:
            conteudo += [tabela([[p("ESPECIFICAÇÃO", pequeno), p("QUANTIDADE", pequeno)]] +
                [[p(l["nome"]), p(l["quantidade"])] for l in registro.recuperados], [largura*.8, largura*.2], cabecalho=True)]
            conteudo += [p("Somente os componentes listados foram retirados da configuração e recebidos no estoque por reaproveitamento, vinculados a esta baixa.", pequeno)]
        else:
            conteudo += [p("Nenhum componente recuperado. Esta baixa não gerou entrada de peças no estoque.")]
        conteudo += [CondPageBreak(100), p("Registro da baixa", secao),
            p("O equipamento foi marcado como Baixado no GESTATI. Cadastro, departamento de vínculo e histórico foram preservados. As peças não selecionadas não foram recebidas no estoque.")]
        emprestimo = getattr(registro, "emprestimo_encerrado", None)
        if emprestimo:
            conteudo += [p(f"O empréstimo {emprestimo.pk}, com destino temporário {emprestimo.nome_destino}, foi encerrado automaticamente por esta baixa, sem registro de devolução física.")]
        conteudo += [Spacer(1, 12*mm), p("Conferência / assinatura: __________________________________________________", pequeno)]

        def rodape(canvas, documento):
            canvas.saveState()
            canvas.setStrokeColor(colors.HexColor("#DAE4E2"))
            canvas.line(18*mm, 16*mm, A4[0]-18*mm, 16*mm)
            canvas.setFont("Gestati", 7)
            canvas.setFillColor(ink)
            canvas.drawString(18*mm, 12*mm, f"GESTATI - Baixa {registro.pk} | Emitido em {emitido}")
            canvas.drawRightString(A4[0]-18*mm, 12*mm, f"Página {documento.page}")
            canvas.restoreState()

        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
            topMargin=18*mm, bottomMargin=22*mm, title=f"GESTATI - Baixa {registro.pk}", author="GESTATI")
        doc.build(conteudo, onFirstPage=rodape, onLaterPages=rodape)
        return buffer.getvalue()
