from django.db import models
from django.utils import timezone
from django.conf import settings
from datetime import date
    

class MacroCategoria(models.Model):
    """
    Agrupador principal para facilitar a visualização em Dashboards e Orçamentos.
    """
    class Tipo(models.TextChoices):
        RECEITA = 'receita', 'Receita'
        DESPESA = 'despesa', 'Despesa'
        RESERVADO = 'reservado', 'Reservado'

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='macro_categorias')
    nome = models.CharField(max_length=100)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    ativo = models.BooleanField(default=True, help_text="Se falso, oculta nos formulários de lançamento")
    ordem = models.PositiveIntegerField(default=0, help_text="Para ordenar no frontend (ex: Moradia primeiro)")

    class Meta:
        verbose_name = 'Macro Categoria'
        verbose_name_plural = 'Macro Categorias'
        ordering = ['tipo', 'ordem', 'nome']
        unique_together = ['usuario', 'nome', 'tipo']

    def __str__(self) -> str:
        return f"{self.nome} ({self.get_tipo_display()})"


class Categoria(models.Model):
    """
    Representa a classificação financeira de uma transação.
    Cada usuário possui seu próprio conjunto de categorias.
    """
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='categorias')
    macro_categoria = models.ForeignKey(MacroCategoria, on_delete=models.CASCADE, related_name='subcategorias')
    
    nome = models.CharField(max_length=100)
    icone = models.CharField(max_length=50, default='bi-tag', help_text="Bootstrap Icons")
    ativo = models.BooleanField(default=True, help_text="Permite o usuário 'excluir' visualmente sem quebrar o banco")

    class Meta:
        verbose_name = 'Categoria'
        verbose_name_plural = 'Categorias'
        ordering = ['macro_categoria__nome', 'nome']
        unique_together = ['usuario', 'macro_categoria', 'nome']

    def __str__(self) -> str:
        return f"{self.macro_categoria.nome} > {self.nome}"


class DespesaFixaManager(models.Manager):
    """
    Manager customizado para encapsular lógicas complexas de busca.
    """
    def ativas_na_data(self, data_referencia: date) -> models.QuerySet:
        return self.filter(
            ativo=True,
            data_inicio__lte=data_referencia
        ).exclude(
            data_fim__lt=data_referencia
        )


class DespesaFixa(models.Model):
    """
    Tabela de 'Expectativa'. Define contratos e orçamentos mensais por usuário.
    """
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE,
        related_name='despesas_fixas'
    )
    nome = models.CharField(max_length=100, help_text="Ex: Aluguel, Conta de Luz, Internet")
    valor_previsto = models.DecimalField(max_digits=10, decimal_places=2)
    dia_vencimento = models.PositiveIntegerField(help_text="Dia do mês (1 a 31)")
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name='despesas_fixas_vinculadas')
    ativo = models.BooleanField(default=True, help_text="Desmarque se cancelar este contrato/serviço")
    data_inicio = models.DateField(default=timezone.now)
    data_fim = models.DateField(null=True, blank=True)

    objects = DespesaFixaManager()

    class Meta:
        verbose_name = 'Despesa Fixa'
        verbose_name_plural = 'Despesas Fixas'
        ordering = ['dia_vencimento', 'nome']

    def __str__(self) -> str:
        return f"{self.nome} (Dia {self.dia_vencimento})"


class LoteImportacao(models.Model):
    """
    Rastreia a origem dos dados importados para garantia da linhagem (Data Lineage).
    """
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE,
        related_name='lotes_importacao'
    )
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

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE,
        related_name='transacoes'
    )
    descricao = models.CharField(max_length=200)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    data = models.DateField()
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name='transacoes_vinculadas')
    
    pago = models.BooleanField(default=False)
    fixo = models.BooleanField(default=False)
    importada_automatica = models.BooleanField(default=False)
    
    lote = models.ForeignKey(LoteImportacao, on_delete=models.CASCADE, null=True, blank=True, related_name='transacoes_lote')
    despesa_fixa = models.ForeignKey(DespesaFixa, on_delete=models.SET_NULL, null=True, blank=True, related_name='transacoes_realizadas')
    
    hash_transacao = models.CharField(max_length=64, null=True, blank=True)
    identificador_extrato = models.CharField(
        max_length=255, 
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

    @property
    def is_receita(self):
        return self.categoria.macro_categoria.tipo == 'receita'

    @property
    def valor_formatado(self):
        if self.is_receita:
            return f"+ R$ {self.valor:.2f}"
        return f"- R$ {self.valor:.2f}"

    @property
    def cor_tailwind(self):
        if self.is_receita:
            return "text-emerald-400"
        return "text-red-500"

    class Meta:
        verbose_name = 'Transação'
        verbose_name_plural = 'Transações'
        ordering = ['-data', '-id']
        unique_together = ['usuario', 'identificador_extrato']

    def __str__(self) -> str:
        return f"{self.descricao} - R$ {self.valor} ({self.data.strftime('%d/%m/%Y')})"


class MetaPoupanca(models.Model):
    """
    Acompanhamento de objetivos financeiros por usuário.
    """
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE,
        related_name='metas_poupanca'
    )
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
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE,
        related_name='regras_classificacao'
    )
    palavra_chave = models.CharField(max_length=100, help_text="Ex: UBER, IFOOD, PGTO SALARIO")
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name='regras_vinculadas')
    despesa_vinculada = models.ForeignKey(DespesaFixa, on_delete=models.SET_NULL, null=True, blank=True, related_name='regras_fixas')

    class Meta:
        verbose_name = 'Regra de Classificação'
        verbose_name_plural = 'Regras de Classificação'
        ordering = ['palavra_chave']
        unique_together = ['usuario', 'palavra_chave']

    def __str__(self) -> str:
        return f"{self.palavra_chave} -> {self.categoria.nome}"
    

class PlanejamentoMensal(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    mes = models.IntegerField()
    ano = models.IntegerField()
    receita_esperada = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    class Meta:
        unique_together = ['usuario', 'mes', 'ano']
        verbose_name = 'Planejamento Mensal'

    def __str__(self):
        return f"Planejamento {self.mes}/{self.ano}"

class OrcamentoCategoria(models.Model):
    planejamento = models.ForeignKey(PlanejamentoMensal, on_delete=models.CASCADE, related_name='orcamentos')
    macro_categoria = models.ForeignKey(MacroCategoria, on_delete=models.CASCADE)
    valor_planejado = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    class Meta:
        unique_together = ['planejamento', 'macro_categoria']