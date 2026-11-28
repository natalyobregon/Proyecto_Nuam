from django.urls import path #esta pagina es para que el sistema sepa que urls estan disponibles en la app calificaciones
from . import views

urlpatterns = [
    path('', views.grilla_calificaciones, name='grilla'),
    path('ingresar/', views.ingresar_calificacion, name='ingresar'),
    path('carga-masiva/', views.carga_masiva, name='carga_masiva'),
    path('carga-masiva/plantilla/', views.carga_plantilla, name='carga_plantilla'),
    path('carga-masiva/<int:pk>/', views.carga_detalle, name='carga_detalle'),
    path('carga-masiva/<int:pk>/confirmar/', views.carga_confirmar, name='carga_confirmar'),
    path('<int:pk>/', views.detalle_calificacion, name='detalle'),
    path('<int:pk>/editar/', views.editar_calificacion, name='editar'),
    path('<int:pk>/eliminar/', views.eliminar_calificacion, name='eliminar'),
]