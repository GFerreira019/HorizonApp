from typing import Any
from datetime import date
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from .models import Transacao, Categoria, DespesaFixa, ReceitaPlanejada, LimiteTemporario, PerfilUsuario

User = get_user_model()


class TransacaoForm(forms.ModelForm):
    """
    Formulário principal para registro e edição de transações financeiras.
    Adaptado para uso mobile com classes do Tailwind/Bootstrap nativas.
    """

    pago = forms.BooleanField(
        required=False,
        label="Já foi pago?",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'})
    )
    
    fixo = forms.BooleanField(
        required=False,
        label="É um gasto fixo mensal?",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'})
    )

    data_inicio_fixo = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date', 
            'class': 'form-control text-gray-300 bg-[#0f172a] border-slate-700',
        })
    )
    
    data_fim_fixo = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date', 
            'class': 'form-control text-gray-300 bg-[#0f172a] border-slate-700',
        })
    )

    class Meta:
        model = Transacao
        fields = ['descricao', 'valor', 'data', 'categoria', 'pago', 'fixo']
        
        widgets = {
            'descricao': forms.TextInput(attrs={
                'class': 'form-control form-control-lg fw-bold text-white', 
                'placeholder': 'Ex: Almoço, Uber, Salário...'
            }),
            'valor': forms.NumberInput(attrs={
                'class': 'form-control form-control-lg text-emerald-400 fw-bold', 
                'placeholder': '0.00',
                'step': '0.01'
            }),
            'data': forms.DateInput(attrs={
                'type': 'date', 
                'class': 'form-control text-gray-300'
            }),
            'categoria': forms.Select(attrs={
                'class': 'form-select form-select-lg text-gray-300'
            }),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """
        Inicializa o formulário injetando dados padrão e aplicando 
        o isolamento MULTI-TENANT nos campos de seleção.
        """
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if not self.initial.get('data'):
            self.initial['data'] = date.today()

        if self.instance.pk and self.instance.pago:
            self.fields['valor'].widget.attrs.update({
                'class': 'form-control form-control-lg text-slate-500 bg-slate-800',
            })

        if self.user:
            queryset = Categoria.objects.select_related('macro_categoria').filter(
                usuario=self.user,
                ativo=True,
                macro_categoria__ativo=True
            ).order_by('macro_categoria__ordem', 'nome')
            
            queryset = queryset.exclude(macro_categoria__nome__icontains="A Classificar")
            
            self.fields['categoria'].queryset = queryset

    def clean(self) -> dict[str, Any]:
        """
        Aplica regras de negócio e validações cruzadas entre os campos.
        """
        cleaned_data = super().clean()
        valor = cleaned_data.get('valor')
        data_transacao = cleaned_data.get('data')
        pago = cleaned_data.get('pago')

        if valor is not None and valor < 0:
            self.add_error(
                'valor', 
                "O valor deve ser positivo. O sistema categoriza as saídas automaticamente."
            )

        if pago and data_transacao and data_transacao > date.today():
            self.add_error(
                'data',
                f"Você marcou como 'Pago', mas a data é futura ({data_transacao.strftime('%d/%m/%Y')}). "
                "Pagamentos futuros devem ficar como pendentes."
            )
            
        return cleaned_data


class AuditoriaForm(forms.ModelForm):
    """
    Formulário simplificado e restrito, utilizado exclusivamente 
    na tela de revisão e conciliação de extratos importados.
    """
    class Meta:
        model = Transacao
        fields = ['descricao', 'categoria', 'status_auditoria']
        
        widgets = {
            'descricao': forms.TextInput(attrs={
                'class': 'form-control font-bold text-gray-400 bg-[#0f172a] border-slate-700', 
                'readonly': 'readonly',
                'help_text': 'A descrição original do extrato não pode ser alterada.'
            }),
            'categoria': forms.Select(attrs={
                'class': 'form-select text-gray-300'
            }),
            'status_auditoria': forms.HiddenInput(),
        }

class DespesaFixaForm(forms.ModelForm):
    """
    Formulário para criação e edição de despesas fixas, 
    com campos específicos para controle de recorrência mensal.
    """
    class Meta:
        model = DespesaFixa
        fields = ['nome', 'valor_previsto', 'dia_vencimento', 'categoria', 'data_inicio', 'data_fim']
        widgets = {
            'data_inicio': forms.DateInput(attrs={'type': 'date', 'class': 'form-input-dark'}),
            'data_fim': forms.DateInput(attrs={'type': 'date', 'class': 'form-input-dark'}),
            'valor_previsto': forms.NumberInput(attrs={'step': '0.01', 'class': 'form-input-dark'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields['categoria'].queryset = Categoria.objects.filter(
                usuario=user, 
                macro_categoria__tipo__in=['despesa', 'reservado'],
                ativo=True
            )

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.categoria_id:
            instance.macro_categoria = instance.categoria.macro_categoria
        if commit:
            instance.save()
        return instance


class LimiteTemporarioForm(forms.ModelForm):
    """
    Formulário para criação de um Limite Temporário de Gastos.

    Decisão de design: `data_inicio` e `data_fim` NÃO são expostos como campos
    editáveis pelo usuário. Em vez disso, usamos o campo sintético `duracao` para
    que o backend calcule `data_fim = timezone.now() + timedelta(hours=N)` com o
    relógio do servidor — isso garante consistência de fuso horário e impede
    manipulação client-side, essencial quando o Open Finance for verificar o período.
    """

    DURACAO_CHOICES = [
        ('24h', '24 Horas'),
        ('7d', '7 Dias'),
        ('30d', '30 Dias'),
        ('custom', 'Personalizado (em horas)'),
    ]

    duracao = forms.ChoiceField(
        choices=DURACAO_CHOICES,
        label='Duração',
        widget=forms.Select(attrs={
            'class': 'form-input-dark',
            'id': 'id_duracao_limite',
        }),
    )

    # Campo auxiliar para duração personalizada; validado apenas quando duracao='custom'.
    duracao_custom_horas = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=8760,  # máx 1 ano em horas
        label='Quantidade de horas',
        widget=forms.NumberInput(attrs={
            'class': 'form-input-dark',
            'placeholder': 'Ex: 48',
            'id': 'id_duracao_custom_horas',
        }),
    )

    class Meta:
        model = LimiteTemporario
        # data_inicio e data_fim são calculados na view — nunca expostos ao usuário.
        fields = ['valor_limite', 'categoria_alvo']
        widgets = {
            'valor_limite': forms.NumberInput(attrs={
                'step': '0.01',
                'min': '0.01',
                'class': 'form-input-dark',
                'placeholder': 'Ex: 200.00',
            }),
            'categoria_alvo': forms.Select(attrs={
                'class': 'form-input-dark',
            }),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """
        Inicializa o queryset de categorias com isolamento por usuário (multi-tenant).
        Filtramos apenas despesas/reservas pois limitar receitas não faz sentido.
        """
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Adiciona opção vazia para 'Geral (sem filtro por categoria)'
        self.fields['categoria_alvo'].required = False
        self.fields['categoria_alvo'].empty_label = '🌐 Geral — todas as categorias'

        if user:
            self.fields['categoria_alvo'].queryset = Categoria.objects.filter(
                usuario=user,
                ativo=True,
                macro_categoria__tipo__in=['despesa', 'reservado'],
            ).select_related('macro_categoria').order_by('macro_categoria__nome', 'nome')

    def clean(self) -> dict[str, Any]:
        """
        Valida a consistência entre duracao e duracao_custom_horas.
        O campo `duracao` é necessário para a view calcular data_fim corretamente.
        """
        cleaned_data = super().clean()
        duracao = cleaned_data.get('duracao')
        custom_horas = cleaned_data.get('duracao_custom_horas')

        if duracao == 'custom' and not custom_horas:
            self.add_error(
                'duracao_custom_horas',
                'Informe o número de horas para a duração personalizada.',
            )

        return cleaned_data


class ReceitaPlanejadaForm(forms.ModelForm):
    class Meta:
        model = ReceitaPlanejada
        fields = ['nome', 'valor_previsto', 'dia_recebimento', 'categoria', 'data_inicio', 'data_fim']
        widgets = {
            'data_inicio': forms.DateInput(attrs={'type': 'date', 'class': 'form-input-dark'}),
            'data_fim': forms.DateInput(attrs={'type': 'date', 'class': 'form-input-dark'}),
            'valor_previsto': forms.NumberInput(attrs={'step': '0.01', 'class': 'form-input-dark'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields['categoria'].queryset = Categoria.objects.filter(
                usuario=user,
                macro_categoria__tipo='receita',
                ativo=True,
            )

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.categoria_id:
            instance.macro_categoria = instance.categoria.macro_categoria
        if commit:
            instance.save()
        return instance


# ==============================================================================
# PERFIL DO USUÁRIO
# ==============================================================================

class UsuarioForm(forms.ModelForm):
    """Formulário para editar campos nativos do User (first_name)."""
    class Meta:
        model = User
        fields = ['first_name', 'email']
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'form-input-dark',
                'placeholder': 'Seu nome',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-input-dark',
                'placeholder': 'seu@email.com',
            }),
        }
        labels = {'first_name': 'Nome', 'email': 'E-mail'}


class PerfilUsuarioForm(forms.ModelForm):
    """Formulário para editar campos do PerfilUsuario."""
    class Meta:
        model = PerfilUsuario
        fields = ['data_nascimento', 'sexo', 'telefone', 'foto_perfil', 'telegram_chat_id']
        widgets = {
            'data_nascimento': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-input-dark',
            }),
            'sexo': forms.Select(attrs={
                'class': 'form-input-dark',
            }),
            'telefone': forms.TextInput(attrs={
                'class': 'form-input-dark',
                'placeholder': '(00) 00000-0000',
            }),
            'foto_perfil': forms.ClearableFileInput(attrs={
                'class': 'hidden',
                'accept': 'image/*',
                'id': 'id_foto_perfil',
            }),
            'telegram_chat_id': forms.TextInput(attrs={
                'class': 'form-input-dark',
                'placeholder': 'Ex: 123456789',
            }),
        }
        labels = {
            'data_nascimento': 'Data de Nascimento',
            'sexo': 'Sexo',
            'telefone': 'Telefone',
            'foto_perfil': 'Foto de Perfil',
            'telegram_chat_id': 'Chat ID do Telegram',
        }