from typing import Any
from datetime import date
from django import forms
from django.core.exceptions import ValidationError
from .models import Transacao


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
        Inicializa o formulário injetando dados padrão e ajustando 
        comportamentos dinâmicos de UI baseados no estado da instância.
        """
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Define data de hoje como padrão se não houver data inicial
        if not self.initial.get('data'):
            self.initial['data'] = date.today()

        # Ajuste visual: Se já está salvo no banco e marcado como pago, altera o visual
        if self.instance.pk and self.instance.pago:
            self.fields['valor'].widget.attrs.update({
                'class': 'form-control form-control-lg text-muted bg-light',
            })

    def clean(self) -> dict[str, Any]:
        """
        Aplica regras de negócio e validações cruzadas entre os campos.
        """
        cleaned_data = super().clean()
        valor = cleaned_data.get('valor')
        data_transacao = cleaned_data.get('data')
        pago = cleaned_data.get('pago')

        # 1. Validação de Valor Positivo
        if valor is not None and valor < 0:
            self.add_error(
                'valor', 
                "O valor deve ser positivo. O sistema categoriza as saídas automaticamente."
            )

        # 2. Validação de Coerência Temporal
        if pago and data_transacao and data_transacao > date.today():
            # Dispara um erro de validação limpo. A renderização do ícone 
            # e das cores (SVG, Divs) deve ser tratada exclusivamente no Template (HTML).
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