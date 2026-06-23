from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
    

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

    def count_despesas_fixas_ativas(self, data_ref: date) -> int:
        return DespesaFixa.objects.ativas_na_data(data_ref).filter(
            macro_categoria=self,
            usuario=self.usuario,
        ).count()

    def count_receitas_planejadas_ativas(self, data_ref: date) -> int:
        return ReceitaPlanejada.objects.ativas_na_data(data_ref).filter(
            macro_categoria=self,
            usuario=self.usuario,
        ).count()


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
        """
        Retorna despesas fixas ativas para uma data de referência.
        Registros sem data de início (Envelopes/tem_vencimento=False) são sempre incluídos.
        """
        return self.filter(
            ativo=True,
        ).filter(
            Q(data_inicio__lte=data_referencia) | Q(data_inicio__isnull=True)
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
    tem_vencimento = models.BooleanField(default=False)
    dia_vencimento = models.PositiveIntegerField(null=True, blank=True, help_text="Dia do mês (1 a 31)")
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name='despesas_fixas_vinculadas')
    macro_categoria = models.ForeignKey(
        MacroCategoria,
        on_delete=models.PROTECT,
        related_name='despesas_fixas',
    )
    ativo = models.BooleanField(default=True, help_text="Desmarque se cancelar este contrato/serviço")
    data_inicio = models.DateField(null=True, blank=True, default=timezone.now)
    data_fim = models.DateField(null=True, blank=True)

    objects = DespesaFixaManager()

    class Meta:
        verbose_name = 'Despesa Fixa'
        verbose_name_plural = 'Despesas Fixas'
        ordering = ['dia_vencimento', 'nome']
        indexes = [
            models.Index(fields=['usuario', 'macro_categoria', 'ativo']),
        ]

    def save(self, *args, **kwargs):
        if self.categoria_id:
            if not self.macro_categoria_id:
                self.macro_categoria_id = self.categoria.macro_categoria_id
            elif self.macro_categoria_id != self.categoria.macro_categoria_id:
                raise ValueError(
                    'macro_categoria deve corresponder à macro da subcategoria vinculada.'
                )
        super().save(*args, **kwargs)

    @classmethod
    def agrupar_por_macro(cls, despesas) -> dict:
        """
        Agrupa despesas fixas por macro_categoria_id.
        Retorna {macro_id: {'itens': [{id, nome, valor, categoria_id, categoria_nome, tem_vencimento}], 'soma': Decimal}}.
        """
        grupos = defaultdict(lambda: {'itens': [], 'soma': Decimal('0.00')})
        for despesa in despesas:
            macro_id = despesa.macro_categoria_id
            grupos[macro_id]['itens'].append({
                'id': despesa.id,
                'nome': despesa.nome,
                'valor': despesa.valor_previsto,
                'categoria_id': despesa.categoria_id,
                'categoria_nome': despesa.categoria.nome,
                'tem_vencimento': despesa.tem_vencimento,
            })
            grupos[macro_id]['soma'] += despesa.valor_previsto
        return dict(grupos)

    def __str__(self) -> str:
        return f"{self.nome} (Dia {self.dia_vencimento})"


class ReceitaPlanejadaManager(models.Manager):
    def ativas_na_data(self, data_referencia: date) -> models.QuerySet:
        """
        Retorna receitas planejadas ativas para uma data de referência.
        Registros sem data de início (Envelopes/tem_vencimento=False) são sempre incluídos.
        """
        return self.filter(
            ativo=True,
        ).filter(
            Q(data_inicio__lte=data_referencia) | Q(data_inicio__isnull=True)
        ).exclude(
            data_fim__lt=data_referencia
        )


class ReceitaPlanejada(models.Model):
    """
    Fontes de receita planejadas por macro (ex.: Emprego 1, Emprego 2).
    """
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='receitas_planejadas',
    )
    nome = models.CharField(max_length=100, help_text="Ex: Salário CLT, Freelance")
    valor_previsto = models.DecimalField(max_digits=10, decimal_places=2)
    tem_vencimento = models.BooleanField(default=False)
    dia_recebimento = models.PositiveIntegerField(null=True, blank=True, default=1, help_text="Dia do mês (1 a 31)")
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.CASCADE,
        related_name='receitas_planejadas_vinculadas',
    )
    macro_categoria = models.ForeignKey(
        MacroCategoria,
        on_delete=models.PROTECT,
        related_name='receitas_planejadas',
    )
    ativo = models.BooleanField(default=True)
    data_inicio = models.DateField(null=True, blank=True, default=timezone.now)
    data_fim = models.DateField(null=True, blank=True)

    objects = ReceitaPlanejadaManager()

    class Meta:
        verbose_name = 'Receita Planejada'
        verbose_name_plural = 'Receitas Planejadas'
        ordering = ['dia_recebimento', 'nome']
        indexes = [
            models.Index(fields=['usuario', 'macro_categoria', 'ativo']),
        ]

    def save(self, *args, **kwargs):
        if self.categoria_id:
            if not self.macro_categoria_id:
                self.macro_categoria_id = self.categoria.macro_categoria_id
            elif self.macro_categoria_id != self.categoria.macro_categoria_id:
                raise ValueError(
                    'macro_categoria deve corresponder à macro da subcategoria vinculada.'
                )
        super().save(*args, **kwargs)

    @classmethod
    def agrupar_por_macro(cls, receitas) -> dict:
        """
        Agrupa receitas planejadas por macro_categoria_id.
        Retorna {macro_id: {'itens': [{id, nome, valor, categoria_id, categoria_nome, tem_vencimento}], 'soma': Decimal}}.
        """
        grupos = defaultdict(lambda: {'itens': [], 'soma': Decimal('0.00')})
        for receita in receitas:
            macro_id = receita.macro_categoria_id
            grupos[macro_id]['itens'].append({
                'id': receita.id,
                'nome': receita.nome,
                'valor': receita.valor_previsto,
                'categoria_id': receita.categoria_id,
                'categoria_nome': receita.categoria.nome,
                'tem_vencimento': receita.tem_vencimento,
            })
            grupos[macro_id]['soma'] += receita.valor_previsto
        return dict(grupos)

    def __str__(self) -> str:
        return f"{self.nome} (Dia {self.dia_recebimento})"


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


class ConexaoBancaria(models.Model):
    """
    Armazena o vínculo seguro entre um usuário e uma instituição financeira
    via agregador de dados (Open Finance Brasil).

    O `item_id_externo` é o identificador opaco retornado pelo Pluggy após o
    fluxo de consentimento. Ele nunca expõe credenciais bancárias — é apenas
    uma referência para buscar transações na API do agregador.
    """
    class StatusConexao(models.TextChoices):
        # Mapeamento direto dos estados do item Pluggy para evitar surpresas na integração.
        UPDATED     = 'UPDATED',      'Atualizada'
        UPDATING    = 'UPDATING',     'Sincronizando'
        LOGIN_ERROR = 'LOGIN_ERROR',  'Erro de Login'
        OUTDATED    = 'OUTDATED',     'Desatualizada'
        WAITING_USER_INPUT = 'WAITING_USER_INPUT', 'Aguardando Ação'

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='conexoes_bancarias',
    )
    # Identificador opaco do item no agregador (ex: Pluggy Item ID)
    item_id_externo = models.CharField(
        max_length=100,
        unique=True,
        help_text="Item ID retornado pelo Pluggy após o consentimento do usuário.",
    )
    provider = models.CharField(
        max_length=30,
        default='pluggy',
        help_text="Slug do agregador de dados utilizado (ex: pluggy, belvo).",
    )
    instituicao_nome = models.CharField(
        max_length=100,
        help_text="Nome amigável da instituição (ex: Nubank, Itaú). Preenchido pelo agregador.",
    )
    status = models.CharField(
        max_length=25,
        choices=StatusConexao.choices,
        default=StatusConexao.UPDATED,
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Conexão Bancária'
        verbose_name_plural = 'Conexões Bancárias'
        ordering = ['-criado_em']
        indexes = [
            # Otimiza a query do worker de sync: buscar conexões ativas por usuário.
            models.Index(fields=['usuario', 'status']),
        ]

    @property
    def esta_saudavel(self) -> bool:
        """Conexão está apta para sincronização automática."""
        return self.status == self.StatusConexao.UPDATED

    @property
    def cor_status_tailwind(self) -> str:
        """Classe de cor para o badge de status no template."""
        mapa = {
            self.StatusConexao.UPDATED:     'text-emerald-400',
            self.StatusConexao.UPDATING:    'text-cyan-400',
            self.StatusConexao.LOGIN_ERROR: 'text-red-400',
            self.StatusConexao.OUTDATED:    'text-amber-400',
            self.StatusConexao.WAITING_USER_INPUT: 'text-amber-400',
        }
        return mapa.get(self.status, 'text-slate-400')

    @property
    def icone_status_bootstrap(self) -> str:
        """Ícone Bootstrap para o badge de status."""
        mapa = {
            self.StatusConexao.UPDATED:     'bi-check-circle-fill',
            self.StatusConexao.UPDATING:    'bi-arrow-repeat',
            self.StatusConexao.LOGIN_ERROR: 'bi-x-circle-fill',
            self.StatusConexao.OUTDATED:    'bi-exclamation-triangle-fill',
            self.StatusConexao.WAITING_USER_INPUT: 'bi-exclamation-triangle-fill',
        }
        return mapa.get(self.status, 'bi-question-circle')

    def __str__(self) -> str:
        return f"{self.instituicao_nome} ({self.usuario.username}) — {self.get_status_display()}"


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
    ignorado = models.BooleanField(default=False, help_text="Se True, a transação sofreu soft-delete e será ocultada dos cálculos e dashboards.")
    
    lote = models.ForeignKey(LoteImportacao, on_delete=models.CASCADE, null=True, blank=True, related_name='transacoes_lote')
    despesa_fixa = models.ForeignKey(DespesaFixa, on_delete=models.SET_NULL, null=True, blank=True, related_name='transacoes_realizadas')
    # Vincula a receita planejada que originou esta entrada, análogo a despesa_fixa
    receita_planejada = models.ForeignKey(
        'ReceitaPlanejada',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transacoes_realizadas',
    )
    
    hash_transacao = models.CharField(max_length=64, null=True, blank=True)
    identificador_extrato = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="ID único vindo do banco para evitar duplicatas na importação CSV (Nubank)."
    )
    # Campos do Open Finance — separados do identificador_extrato (Nubank CSV) para
    # garantir separação de preocupações e retrocompatibilidade total com lotes CSV.
    id_transacao_externa = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        unique=True,
        help_text="ID único retornado pelo agregador (Pluggy) para garantir idempotência.",
    )
    conexao_origem = models.ForeignKey(
        'ConexaoBancaria',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transacoes_sincronizadas',
        help_text="Conexão Open Finance que originou esta transação. Nulo = importação CSV.",
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
        # Mantém a unicidade do identificador CSV (Nubank) — não conflita com
        # id_transacao_externa que possui unique=True próprio no campo.
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
    # Receita planejada vinculada à regra, para automação de classificação de entradas
    receita_vinculada = models.ForeignKey(
        ReceitaPlanejada,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='regras_receita',
    )

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
        verbose_name_plural = 'Planejamentos Mensais'

    def __str__(self):
        return f"Planejamento {self.mes}/{self.ano}"

class OrcamentoCategoria(models.Model):
    planejamento = models.ForeignKey(PlanejamentoMensal, on_delete=models.CASCADE, related_name='orcamentos')
    macro_categoria = models.ForeignKey(MacroCategoria, on_delete=models.CASCADE)
    valor_planejado = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    class Meta:
        unique_together = ['planejamento', 'macro_categoria']
        verbose_name = 'Orçamento por Categoria'
        verbose_name_plural = 'Orçamentos por Categoria'


class LimiteTemporarioManager(models.Manager):
    """
    Manager para encapsular a query mais comum: limites ainda dentro da janela temporal.
    Centralizar aqui evita repetir o filtro em views e no futuro worker do Open Finance.
    """
    def ativos_para_usuario(self, usuario) -> models.QuerySet:
        """Retorna limites marcados como ativos E ainda dentro do período definido."""
        return self.filter(
            usuario=usuario,
            ativo=True,
            data_fim__gt=timezone.now(),
        ).select_related('categoria_alvo')


class LimiteTemporario(models.Model):
    """
    Define um teto de gasto com janela temporal específica.

    ARQUITETURA FUTURA:
    - Open Finance: o campo `valor_consumido` será incrementado automaticamente
      quando a API bancária registrar transações na categoria/período deste limite.
    - Telegram: o campo `notificacao_enviada` será verificado por um Celery Beat task
      para disparar o alerta ao usuário apenas uma vez ao atingir o limite.

    O campo `categoria_alvo` sendo nulo representa um limite global (todas as categorias),
    o que permite ao worker do Open Finance aplicar a soma geral de saídas do período.
    """
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='limites_temporarios',
    )
    valor_limite = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Teto de gasto que não deve ser ultrapassado na janela definida.",
    )
    # Preparado para o Open Finance: será preenchido pelo worker de sync bancário.
    valor_consumido = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Valor já gasto dentro deste limite. Atualizado pelo Open Finance.",
    )
    data_inicio = models.DateTimeField(
        default=timezone.now,
        help_text="Momento de criação do limite. Referência para cálculo de expiração.",
    )
    data_fim = models.DateTimeField(
        help_text="Expiração calculada pelo backend (ex: now + 24h). Não editável pelo usuário.",
    )
    # Nulo = limite global (todas as categorias). Valor = limite por categoria específica.
    categoria_alvo = models.ForeignKey(
        Categoria,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='limites_temporarios',
        help_text="Se nulo, o limite aplica-se a todos os gastos do usuário no período.",
    )
    # Preparado para o Telegram: o worker de notificação seta True após enviar o alerta.
    notificacao_enviada = models.BooleanField(
        default=False,
        help_text="Evita alertas duplicados. Setado como True pelo bot do Telegram após o disparo.",
    )
    ativo = models.BooleanField(
        default=True,
        help_text="Soft-delete: False = limite cancelado/expirado manualmente pelo usuário.",
    )

    objects = LimiteTemporarioManager()

    class Meta:
        verbose_name = 'Limite Temporário'
        verbose_name_plural = 'Limites Temporários'
        ordering = ['data_fim']
        indexes = [
            # Índice composto otimizado para a query mais frequente do Open Finance:
            # filtrar limites ativos de um usuário dentro de uma janela temporal.
            models.Index(fields=['usuario', 'ativo', 'data_fim']),
        ]

    def __str__(self) -> str:
        alvo = self.categoria_alvo.nome if self.categoria_alvo else 'Geral'
        return f"Limite R$ {self.valor_limite} em {alvo} (até {self.data_fim.strftime('%d/%m %H:%M')})"

    @property
    def percentual_consumido(self) -> float:
        """
        Percentual de consumo em relação ao limite definido.
        Exposto para o template e para o worker do Telegram calcular o threshold de alerta.
        """
        if not self.valor_limite or self.valor_limite == Decimal('0.00'):
            return 0.0
        return round(float(self.valor_consumido / self.valor_limite * 100), 1)

    @property
    def esta_expirado(self) -> bool:
        """Verifica expiração temporal sem depender do campo `ativo`."""
        return timezone.now() > self.data_fim

    @property
    def tempo_restante_segundos(self) -> int:
        """Segundos restantes para expiração. Negativo se já expirou."""
        delta = self.data_fim - timezone.now()
        return int(delta.total_seconds())

    @property
    def cor_status_tailwind(self) -> str:
        """
        Classe de cor para o template.
        Threshold de 80% é o gatilho de alerta do Telegram — mantemos coerência visual.
        """
        pct = self.percentual_consumido
        if pct >= 100:
            return 'text-red-400'
        if pct >= 80:
            return 'text-amber-400'
        return 'text-emerald-400'

    @property
    def cor_barra_tailwind(self) -> str:
        """Classe de cor para a barra de progresso de consumo."""
        pct = self.percentual_consumido
        if pct >= 100:
            return 'bg-red-500'
        if pct >= 80:
            return 'bg-amber-400'
        return 'bg-cyan-500'


class PerfilUsuario(models.Model):
    """
    Extensão do modelo User do Django via OneToOne.
    Armazena dados de personalização e integrações externas do usuário.
    """
    class Sexo(models.TextChoices):
        MASCULINO = 'M', 'Masculino'
        FEMININO = 'F', 'Feminino'
        OUTRO = 'O', 'Outro'

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='perfil',
    )
    data_nascimento = models.DateField(null=True, blank=True)
    sexo = models.CharField(max_length=1, choices=Sexo.choices, null=True, blank=True)
    telefone = models.CharField(max_length=20, null=True, blank=True)
    foto_perfil = models.ImageField(upload_to='perfis/', null=True, blank=True)
    telegram_chat_id = models.CharField(
        max_length=50, null=True, blank=True,
        help_text="ID do chat do Telegram para notificações do Guardião",
    )

    class Meta:
        verbose_name = 'Perfil do Usuário'
        verbose_name_plural = 'Perfis de Usuários'

    def __str__(self) -> str:
        return f"Perfil de {self.usuario.get_full_name() or self.usuario.username}"