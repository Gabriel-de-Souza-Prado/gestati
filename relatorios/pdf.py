"""Exportação completa da consulta, sem alterar registros nem executar operações."""
from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from core.pdf import LOCK_GERACAO_PDF


def gerar_pdf_relatorio(*, definicao, linhas, filtros, emitido_em, emitido_por):
    with LOCK_GERACAO_PDF:
        buffer = BytesIO()
        pagina = landscape(A4)
        largura = pagina[0] - 28*mm
        instante = timezone.localtime(emitido_em).strftime("%d/%m/%Y %H:%M")
        ink, teal = colors.HexColor("#203642"), colors.HexColor("#08796E")
        corpo = ParagraphStyle("RelatorioCorpo", fontName="Gestati", fontSize=8.5, leading=12, textColor=ink, spaceAfter=5)
        titulo = ParagraphStyle("RelatorioTitulo", parent=corpo, fontName="GestatiBold", fontSize=22, leading=28, spaceAfter=9)
        cabecalho = ParagraphStyle("RelatorioCabecalho", parent=corpo, fontName="GestatiBold", textColor=colors.white, fontSize=8, leading=11)
        pequeno = ParagraphStyle("RelatorioPequeno", parent=corpo, fontSize=7.5, leading=10.5)

        def p(valor, estilo=corpo):
            return Paragraph(escape(str(valor).replace("→", "para")).replace("\n", "<br/>"), estilo)

        conteudo = [p("GESTATI | RELATÓRIOS", pequeno), p(definicao.titulo, titulo), p(definicao.descricao),
                    p(f"Emitido em {instante} | Por {emitido_por} | {len(linhas)} registro(s)", pequeno)]
        for filtro in filtros:
            conteudo.append(p(filtro, pequeno))
        if not filtros:
            conteudo.append(p("Sem filtros adicionais.", pequeno))
        conteudo.append(Spacer(1, 5*mm))
        if linhas:
            larguras = [largura * peso / sum(definicao.larguras) for peso in definicao.larguras]
            tabela_linhas = [[p(c, cabecalho) for c in definicao.colunas]]
            # Uma célula pode conter centenas de peças/participantes. Dividir
            # essas células antes da tabela preserva a identificação em cada
            # continuação e evita cabeçalho repetido no meio da mesma página.
            for valores in linhas:
                partes = []
                for valor, coluna_largura in zip(valores, larguras):
                    atual, pedacos = p(valor), []
                    while atual.wrap(coluna_largura-14, 210)[1] > 210:
                        primeiro, atual = atual.split(coluna_largura-14, 210)
                        pedacos.append(primeiro)
                    pedacos.append(atual)
                    partes.append(pedacos)
                for numero in range(max(map(len, partes))):
                    celulas = []
                    for indice, pedacos in enumerate(partes):
                        if len(pedacos) == 1:
                            celula = p(f"{valores[0]}\n(continuação)") if numero and indice == 0 else pedacos[0]
                        else:
                            celula = pedacos[numero] if numero < len(pedacos) else p("")
                        celulas.append(celula)
                    tabela_linhas.append(celulas)
            tabela = LongTable(tabela_linhas, colWidths=larguras,
                repeatRows=1, hAlign="LEFT", splitByRow=1)
            tabela.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), teal),
                ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F1F6F5")]),
                ("VALIGN", (0,0), (-1,-1), "TOP"),
                ("LEFTPADDING", (0,0), (-1,-1), 7), ("RIGHTPADDING", (0,0), (-1,-1), 7),
                ("TOPPADDING", (0,0), (-1,-1), 7), ("BOTTOMPADDING", (0,0), (-1,-1), 6),
                ("LINEBELOW", (0,0), (-1,0), .5, teal),
                ("LINEBELOW", (0,1), (-1,-1), .25, colors.HexColor("#DCE5E9")),
            ]))
            conteudo.append(tabela)
        else:
            conteudo.append(p("Nenhum registro encontrado para os filtros informados."))

        def rodape(canvas, documento):
            canvas.saveState()
            canvas.setStrokeColor(colors.HexColor("#DAE4E2"))
            canvas.line(14*mm, 13*mm, pagina[0]-14*mm, 13*mm)
            canvas.setFont("Gestati", 7)
            canvas.setFillColor(ink)
            canvas.drawString(14*mm, 9*mm, f"GESTATI - {definicao.titulo} | {instante}")
            canvas.drawRightString(pagina[0]-14*mm, 9*mm, f"Página {documento.page}")
            canvas.restoreState()

        doc = SimpleDocTemplate(buffer, pagesize=pagina, leftMargin=14*mm, rightMargin=14*mm,
            topMargin=14*mm, bottomMargin=19*mm, title=f"GESTATI - {definicao.titulo}", author="GESTATI")
        doc.build(conteudo, onFirstPage=rodape, onLaterPages=rodape)
        return buffer.getvalue()
