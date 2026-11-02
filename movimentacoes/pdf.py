"""Documento de transferência: lê somente o evento preservado."""
from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import CondPageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.pdf import LOCK_GERACAO_PDF


def gerar_pdf_transferencia(registro):
    with LOCK_GERACAO_PDF:
        buffer = BytesIO()
        largura = A4[0] - 36*mm
        emitido = timezone.localtime().strftime("%d/%m/%Y %H:%M")
        instante = timezone.localtime(registro.registrado_em).strftime("%d/%m/%Y %H:%M")
        ink = colors.HexColor("#203642")
        corpo = ParagraphStyle("TransferenciaCorpo", fontName="Gestati", fontSize=10, leading=15, spaceAfter=8, textColor=ink)
        pequeno = ParagraphStyle("TransferenciaPequeno", parent=corpo, fontSize=8, leading=12)
        titulo = ParagraphStyle("TransferenciaTitulo", parent=corpo, fontName="GestatiBold", fontSize=21, leading=27, spaceAfter=14)
        secao = ParagraphStyle("TransferenciaSecao", parent=corpo, fontName="GestatiBold", fontSize=12, leading=17, textColor=colors.HexColor("#08796E"), spaceBefore=12)

        def p(texto, estilo=corpo):
            return Paragraph(escape(str(texto or "Não informado")).replace("\n", "<br/>"), estilo)

        def campo(rotulo, valor):
            return Paragraph(f"<b>{escape(rotulo)}</b><br/>{escape(str(valor or 'Não informado'))}", corpo)

        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
                                topMargin=18*mm, bottomMargin=22*mm,
                                title=f"GESTATI - Transferência {registro.pk}", author="GESTATI")
        conteudo = [p("GESTATI | Gestão de itens de TI", pequeno), p("Transferência de equipamento", titulo),
                    p(f"Registro {registro.pk} | {instante}", pequeno)]
        linhas = [
            [campo("EQUIPAMENTO", registro.descricao_ativo), campo("DTI", registro.dti_ativo)],
            [campo("PATRIMÔNIO", registro.patrimonio_ativo), campo("NÚMERO DE SÉRIE", registro.serie_ativo)],
            [campo("DEPARTAMENTO DE ORIGEM", registro.nome_origem), campo("DEPARTAMENTO DE DESTINO", registro.nome_destino)],
            [campo("REGISTRADO POR", registro.nome_tecnico), campo("REGISTRADO EM", instante)],
        ]
        tabela = Table(linhas, colWidths=[largura*.52, largura*.48], hAlign="LEFT")
        tabela.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#F1F6F5")),
            ("VALIGN",(0,0),(-1,-1),"TOP"), ("LEFTPADDING",(0,0),(-1,-1),10),
            ("RIGHTPADDING",(0,0),(-1,-1),10), ("TOPPADDING",(0,0),(-1,-1),8),
            ("BOTTOMPADDING",(0,0),(-1,-1),5)]))
        conteudo += [tabela, CondPageBreak(70), p("Motivo da transferência", secao), p(registro.motivo),
                     CondPageBreak(95), p("Registro da mudança de vínculo", secao),
                     p(f"O equipamento identificado acima teve seu departamento de vínculo alterado de {registro.nome_origem} para {registro.nome_destino} no GESTATI.")]
        emprestimo = getattr(registro, "emprestimo_encerrado", None)
        if emprestimo:
            conteudo += [p(f"Esta transferência tornou definitivo o empréstimo {emprestimo.pk}, encerrado sem registro de devolução física.")]
        conteudo += [Spacer(1,14*mm), p("Conferência / assinatura: __________________________________________________", pequeno)]

        def rodape(canvas, documento):
            canvas.saveState()
            canvas.setStrokeColor(colors.HexColor("#DAE4E2"))
            canvas.line(18*mm,16*mm,A4[0]-18*mm,16*mm)
            canvas.setFont("Gestati",7)
            canvas.setFillColor(ink)
            canvas.drawString(18*mm,12*mm,f"GESTATI - Transferência {registro.pk} | Emitido em {emitido}")
            canvas.drawRightString(A4[0]-18*mm,12*mm,f"Página {documento.page}")
            canvas.restoreState()

        doc.build(conteudo,onFirstPage=rodape,onLaterPages=rodape)
        return buffer.getvalue()
