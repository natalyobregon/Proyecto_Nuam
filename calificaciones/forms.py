from django import forms
from .models import Calificacion


class CalificacionBasicaForm(forms.ModelForm):
    class Meta:
        model = Calificacion
        fields = [
            'mercado',
            'instrumento',
            'secuencia_evento',
            'dividendo',
            'fecha_pago',
            'valor_historico',
            'ejercicio',
            'descripcion',
        ]
        widgets = {
            'mercado': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: Acciones, RV, etc.',
            }),
            'instrumento': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: SQM-B, COPEC',
            }),
            'secuencia_evento': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 10001,
            }),
            'dividendo': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
            }),
            'fecha_pago': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
            }),
            'valor_historico': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
            }),
            'ejercicio': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1900,
                'max': 2100,
            }),
            'descripcion': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Opcional',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Según el diseño, solo descripción (y factor_actualizacion) son opcionales;
        # el resto de los campos básicos son obligatorios.
        obligatorios = [
            'mercado',
            'instrumento',
            'secuencia_evento',
            'dividendo',
            'fecha_pago',
            'valor_historico',
            'ejercicio',
        ]
        for campo in obligatorios:
            self.fields[campo].required = True

    def clean_secuencia_evento(self):
        secuencia = self.cleaned_data['secuencia_evento']
        if secuencia <= 10000:
            raise forms.ValidationError('La secuencia del evento debe ser mayor a 10.000.')
        return secuencia