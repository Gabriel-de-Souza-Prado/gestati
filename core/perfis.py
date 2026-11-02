from django.db.models import TextChoices


class PerfilConfiguracao(TextChoices):
    GENERICO = "generico", "Genérico"
    COMPUTADOR = "computador", "Computador"
    NOTEBOOK = "notebook", "Notebook"
    MONITOR = "monitor", "Monitor"
    NOBREAK = "nobreak", "Nobreak"
    IMPRESSORA = "impressora", "Impressora"
    SWITCH = "switch", "Switch"
