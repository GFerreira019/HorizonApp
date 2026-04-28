from django.db import models
from django.utils import timezone
from datetime import date

class Categoria(models.Model):
    """
    Representa a classificação financeira de uma transação.
    """
    class TipoCategoria(models.TextChoices):
        RECEITA = 'receita', 'Receita'
        DESPESA = 'despesa', 'Despesa'

    nome = models.CharField(max_length=100)
    icone = models.CharField(max_length=50, help_text="Ex: bi-house-door (Bootstrap Icons)")
    tipo = models.CharField(max_length=10, choices=TipoCategoria.choices)

    class Meta:
        verbose_name = 'Categoria'
        verbose_name_plural = 'Categorias'
        ordering = ['nome']

    def __str__(self) -> str:
        return f"{self.nome} ({self.get_tipo_display()})"


class DespesaFixaManager(models.Manager):
    """
    Manager customizado para encapsular lógicas complexas de busca.
    """
    def ativas_na_data(self, data_referencia: date) -> models.QuerySet:
        """
        Retorna despesas que estão ativas e válidas para a data informada,
        evitando bugs com datas futuras ou despesas já encerradas.
        """
        return self.filter(
            ativo=True,
            data_inicio__lte=data_referencia
        ).exclude(
            data_fim__lt=data_referencia
        )


class DespesaFixa(models.Model):
    """
    Tabela de 'Expectativa'. Define contratos, prazos e orçamentos mensais.
    """
    nome = models.CharField(max_length=100, help_text="Ex: Aluguel, Conta de Luz, Internet")
    valor_previsto = models.DecimalField(max_digits=10, decimal_places=2)
    dia_vencimento = models.PositiveIntegerField(help_text="Dia do mês (1 a 31)")
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name='despesas_fixas')
    ativo = models.BooleanField(default=True, help_text="Desmarque se cancelar este contrato/serviço")
    data_inicio = models.DateField(default=timezone.now)
    data_fim = models.DateField(null=True, blank=True, help_text="Preencha apenas se houver previsão de término")

    objects = DespesaFixaManager()

    class Meta:
        verbose_name = 'Despesa Fixa'
        verbose_name_plural = 'Despesas Fixas'
        ordering = ['dia_vencimento', 'nome']

    def __str__(self) -> str:
        return f"{self.nome} (Dia {self.dia_vencimento})"


class LoteImportacao(models.Model):
    """
    Rastreia a origem dos dados importados (arquivos CSV) para garantia da linhagem (Data Lineage).
    """
    data_importacao = models.DateTimeField(auto_now_add=True)
    arquivo_nome = models.CharField(max_length=255)
    
    class Meta:
        verbose_name = 'Lote de Importação'
        verbose_name_plural = 'Lotes de Importação'
        ordering = ['-data_importacao']

    def __str__(self) -> str:
        data_formatada = self.data_importacao.strftime('%d/%m/%Y %H:%M')
        return f"{self.arquivo_nome} em {data_formatada}"


class Transacao(models.Model):
    """
    Tabela de 'Fatos'. Registra o fluxo de caixa real (entradas e saídas).
    """
    class StatusAuditoria(models.TextChoices):
        PENDENTE = 'pendente', 'Pendente de Revisão'
        CONSOLIDADO = 'consolidado', 'Consolidado'

    descricao = models.CharField(max_length=200)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    data = models.DateField()
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name='transacoes')
    
    # Flags de controle
    pago = models.BooleanField(default=False)
    fixo = models.BooleanField(default=False)
    importada_automatica = models.BooleanField(default=False)
    
    # Relacionamentos
    lote = models.ForeignKey(LoteImportacao, on_delete=models.CASCADE, null=True, blank=True, related_name='transacoes')
    despesa_fixa = models.ForeignKey(DespesaFixa, on_delete=models.SET_NULL, null=True, blank=True, related_name='transacoes_vinculadas')
    
    # Rastreabilidade e Auditoria
    hash_transacao = models.CharField(max_length=64, unique=True, null=True, blank=True)
    identificador_extrato = models.CharField(
        max_length=255, 
        unique=True, 
        null=True, 
        blank=True, 
        help_text="ID único vindo do banco para evitar duplicatas na importação"
    )
    status_auditoria = models.CharField(
        max_length=15, 
        choices=StatusAuditoria.choices, 
        default=StatusAuditoria.PENDENTE
    )
    motivo_auditoria = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        verbose_name = 'Transação'
        verbose_name_plural = 'Transações'
        ordering = ['-data', '-id']

    def __str__(self) -> str:
        return f"{self.descricao} - R$ {self.valor} ({self.data.strftime('%d/%m/%Y')})"


class MetaPoupanca(models.Model):
    """
    Acompanhamento de objetivos financeiros.
    """
    objetivo = models.CharField(max_length=100)
    valor_meta = models.DecimalField(max_digits=10, decimal_places=2)
    valor_atual = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    class Meta:
        verbose_name = 'Meta de Poupança'
        verbose_name_plural = 'Metas de Poupança'

    def __str__(self) -> str:
        percentual = (self.valor_atual / self.valor_meta * 100) if self.valor_meta else 0
        return f"{self.objetivo}: {percentual:.1f}% concluído"


class RegraClassificacao(models.Model):
    """
    Motor de automação que categoriza gastos via palavras-chave (Regex/Like).
    """
    palavra_chave = models.CharField(max_length=100, help_text="Ex: UBER, IFOOD, PGTO SALARIO")
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name='regras')
    despesa_vinculada = models.ForeignKey(DespesaFixa, on_delete=models.SET_NULL, null=True, blank=True, related_name='regras')

    class Meta:
        verbose_name = 'Regra de Classificação'
        verbose_name_plural = 'Regras de Classificação'
        ordering = ['palavra_chave']

    def __str__(self) -> str:
        return f"{self.palavra_chave} -> {self.categoria.nome}"