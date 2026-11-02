"""Apresentação da OS em A4. Apenas leitura; imprimir não altera o atendimento."""
from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import CondPageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


from core.pdf import LOCK_GERACAO_PDF as _PDF_LOCK
from .selectors import registros_para_apresentacao


def _data(valor):
    return timezone.localtime(valor).strftime("%d/%m/%Y %H:%M") if valor else "Pendente"


def gerar_pdf_os(ordem):
    # ReportLab compartilha caches internos. Serializar a geração entre threads
    # do mesmo processo evita geração concorrente sobre esses caches.
    with _PDF_LOCK:
        return _gerar(ordem)


def _gerar(ordem):
    buffer = BytesIO()
    emitido = timezone.localtime().strftime("%d/%m/%Y %H:%M")
    teal = colors.HexColor("#08796E")
    ink = colors.HexColor("#203642")
    corpo = ParagraphStyle("CorpoGestati", fontName="Gestati", fontSize=9, leading=13, textColor=ink, spaceAfter=4)
    pequeno = ParagraphStyle("PequenoGestati", parent=corpo, fontSize=8, leading=12)
    titulo = ParagraphStyle("TituloGestati", parent=corpo, fontName="GestatiBold", fontSize=21, leading=27, spaceAfter=12)
    secao = ParagraphStyle("SecaoGestati", parent=corpo, fontName="GestatiBold", fontSize=11, leading=16, textColor=teal, spaceBefore=10, spaceAfter=5)

    def p(texto, estilo=corpo):
        return Paragraph(escape(str(texto or "Não informado")).replace("\n", "<br/>"), estilo)

    def campo(rotulo, valor):
        return Paragraph(f"<b>{escape(rotulo)}</b><br/>{escape(str(valor or 'Não informado'))}", corpo)

    def h(texto):
        # Reserva espaço para o título e as primeiras linhas, sem arrastar
        # um parágrafo longo inteiro para a página seguinte.
        return [CondPageBreak(70), p(texto, secao)]

    largura = A4[0] - 36 * mm
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
                            topMargin=18*mm, bottomMargin=20*mm,
                            title=f"GESTATI - OS {ordem.pk}", author="GESTATI")
    conteudo = [p("GESTATI | Ordem de serviço", pequeno), p(f"OS {ordem.pk}", titulo)]
    resumo = Table([
        [campo("ETAPA", ordem.get_status_display()), campo("ABERTURA", _data(ordem.aberto_em))],
        [campo("EQUIPAMENTO", ordem.nome_ativo), campo("DTI", ordem.dti_ativo)],
        [campo("PATRIMÔNIO", ordem.patrimonio_ativo), campo("NÚMERO DE SÉRIE", ordem.serie_ativo)],
        [campo("MODELO", ordem.modelo_ativo), campo("DEPARTAMENTO", ordem.nome_departamento)],
        [campo("QUEM ENTREGOU", ordem.entregue_por), campo("REGISTRADO POR", ordem.nome_tecnico_abertura)],
    ], colWidths=[largura*.56, largura*.44], hAlign="LEFT")
    resumo.setStyle(TableStyle([("BACKGROUND", (0,0),(-1,-1), colors.HexColor("#F1F6F5")),
                                ("VALIGN",(0,0),(-1,-1),"TOP"), ("LEFTPADDING",(0,0),(-1,-1),10),
                                ("RIGHTPADDING",(0,0),(-1,-1),10), ("TOPPADDING",(0,0),(-1,-1),5),
                                ("BOTTOMPADDING",(0,0),(-1,-1),5)]))
    conteudo += [resumo, *h("Problema informado"), p(ordem.problema)]
    if ordem.garantia_na_abertura:
        conteudo += [*h("Atenção à garantia"), p(f"Equipamento dentro da garantia informada na abertura, até {ordem.fim_garantia:%d/%m/%Y}. Fornecedor: {ordem.nome_fornecedor or 'não informado'}. Consulte o fornecedor antes de intervir.")]
    registros = registros_para_apresentacao(ordem)
    for registro in registros:
        cabecalho = f"{registro.get_tipo_display()} | {_data(registro.registrado_em)}"
        conteudo += [*h(cabecalho), p(f"Técnico: {registro.nome_tecnico}", pequeno), p(registro.descricao_exibicao)]
        if registro.revisao_atual:
            conteudo += [p(f"Editado em {_data(registro.revisao_atual.registrado_em)} por {registro.revisao_atual.nome_tecnico}. Motivo: {registro.revisao_atual.justificativa}", pequeno)]
        itens = registro.pecas_exibicao
        if itens:
            linhas = [[p("COMPONENTE", pequeno), p("AÇÃO / ORIGEM", pequeno), p("QTD.", pequeno)]]
            for item in itens:
                linhas.append([p(item["nome"], pequeno), p(item["rotulo"], pequeno), p(item["quantidade"], pequeno)])
            tabela = Table(linhas, colWidths=[largura*.48, largura*.40, largura*.12], repeatRows=1, hAlign="LEFT")
            tabela.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"), ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#EDF3F2")),
                                      ("LINEBELOW",(0,0),(-1,-1),.3,colors.HexColor("#DAE4E2")),
                                      ("TOPPADDING",(0,0),(-1,-1),6), ("BOTTOMPADDING",(0,0),(-1,-1),4)]))
            conteudo += [tabela, Spacer(1, 3*mm)]
    conteudo += [*h("Conclusão e devolução")]
    conclusao = Table([
        [campo("RESULTADO", ordem.get_resultado_display() if ordem.resultado else "Trabalho técnico pendente"), campo("CONCLUSÃO TÉCNICA", _data(ordem.concluido_em))],
        [campo("ENCERRAMENTO", _data(ordem.encerrado_em)), campo("QUEM RECEBEU NA DEVOLUÇÃO", "Dispensado: encerrada para baixa" if ordem.encerrada_para_baixa else (ordem.recebido_por or "Devolução pendente"))],
    ], colWidths=[largura*.5, largura*.5], hAlign="LEFT")
    conclusao.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"), ("LEFTPADDING",(0,0),(-1,-1),0), ("TOPPADDING",(0,0),(-1,-1),5)]))
    conteudo += [conclusao]
    if ordem.encerrada_para_baixa:
        conteudo += [p("OS encerrada para baixa, sem retirada. O ativo está Sem reparo. A baixa do equipamento exige confirmação separada.")]

    def rodape(canvas, documento):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#DAE4E2"))
        canvas.line(18*mm, 16*mm, A4[0]-18*mm, 16*mm)
        canvas.setFont("Gestati", 7)
        canvas.setFillColor(ink)
        canvas.drawString(18*mm, 12*mm, f"GESTATI - OS {ordem.pk} | Emitido em {emitido}")
        canvas.drawRightString(A4[0]-18*mm, 12*mm, f"Página {documento.page}")
        canvas.restoreState()

    doc.build(conteudo, onFirstPage=rodape, onLaterPages=rodape)
    return buffer.getvalue()
