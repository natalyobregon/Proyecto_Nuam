from django.urls import path #esta pagina es para que el sistema sepa que urls estan disponibles en la app calificaciones
from . import views

urlpatterns = [
    path('', views.grilla_calificaciones, name='grilla'),
    path('ingresar/', views.ingresar_calificacion, name='ingresar'),
    path('<int:pk>/', views.detalle_calificacion, name='detalle'),
]