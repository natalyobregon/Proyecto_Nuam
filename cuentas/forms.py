from django import forms


class LoginForm(forms.Form):
    username = forms.CharField(
        label='Usuario', max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control', 'autocomplete': 'username', 'autofocus': True,
            'autocapitalize': 'none', 'spellcheck': 'false'}))
    password = forms.CharField(
        label='Contraseña', max_length=128, strip=False,
        widget=forms.PasswordInput(render_value=False, attrs={
            'class': 'form-control', 'autocomplete': 'current-password'}))
