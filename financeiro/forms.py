from typing import Any
from datetime import date
from django import forms
from django.core.exceptions import ValidationError
from .models import Transacao, Categoria, DespesaFixa


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
                macro_categoria__tipo='despesa',
                ativo=True
            )