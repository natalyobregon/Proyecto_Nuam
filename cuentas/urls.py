from django.urls import path

from . import views

app_name = 'cuentas'

urlpatterns = [
    path('', views.login_view, name='login'),
    path('salir/', views.logout_view, name='logout'),
]
