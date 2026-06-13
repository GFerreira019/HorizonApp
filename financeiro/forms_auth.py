from django import forms
from .models import PerfilUsuario


class CustomSignupForm(forms.Form):
    """
    Formulário extra para ser renderizado durante o signup do allauth.
    Estende o cadastro coletando Nome, Telefone, Data de Nascimento, Sexo e Foto de Perfil.
    """
    nome = forms.CharField(
        max_length=150,
        required=True,
        label='Nome',
        widget=forms.TextInput(attrs={'placeholder': 'Seu nome'}),
    )
    telefone = forms.CharField(
        max_length=20,
        required=False,
        label='Telefone',
        widget=forms.TextInput(attrs={'placeholder': '(00) 00000-0000'}),
    )
    data_nascimento = forms.DateField(
        required=False,
        label='Data de Nascimento',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    sexo = forms.ChoiceField(
        required=False,
        label='Sexo',
        choices=[('', '---')] + list(PerfilUsuario.Sexo.choices),
    )
    foto_perfil = forms.ImageField(
        required=False,
        label='Foto de Perfil',
        widget=forms.ClearableFileInput(attrs={'accept': 'image/*', 'id': 'id_foto_perfil'}),
    )

    def signup(self, request, user):
        """
        Método obrigatório do allauth quando usando ACCOUNT_SIGNUP_FORM_CLASS.
        É chamado após o User ser salvo no banco.
        """
        # Salva o nome no model User
        user.first_name = self.cleaned_data['nome']
        user.save(update_fields=['first_name'])
        
        # O signal post_save já cria o perfil vazio. Vamos apenas atualizá-lo.
        perfil = user.perfil
        perfil.telefone = self.cleaned_data.get('telefone')
        perfil.data_nascimento = self.cleaned_data.get('data_nascimento')
        perfil.sexo = self.cleaned_data.get('sexo') or None
        perfil.foto_perfil = self.cleaned_data.get('foto_perfil')
        
        update_fields = ['telefone', 'data_nascimento', 'sexo']
        if perfil.foto_perfil:
            update_fields.append('foto_perfil')
            
        perfil.save(update_fields=update_fields)
