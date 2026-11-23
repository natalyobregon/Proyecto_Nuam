from django.urls import path
from . import views

urlpatterns = [
    path('', views.grilla_calificaciones, name='grilla'),
    path('ingresar/', views.ingresar_calificacion, name='ingresar'),
]