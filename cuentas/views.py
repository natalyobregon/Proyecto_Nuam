from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .alcance import calificaciones_visibles
from .forms import LoginForm
from .permisos import INGRESAR, tiene_permiso
from .servicios import auditar, iniciar_sesion


def _destino_seguro(request):
    """Solo se acepta `next` si apunta a este mismo sitio (evita redireccion abierta)."""
    destino = request.POST.get('next') or request.GET.get('next') or ''
    if destino and url_has_allowed_host_and_scheme(
            destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return destino
    return 'grilla'


@never_cache
@require_http_methods(['GET', 'POST'])
def login_view(request):
    if request.user.is_authenticated:
        return redirect('grilla')

    form = LoginForm(request.POST or None)
    error = None
    if request.method == 'POST' and form.is_valid():
        usuario, error = iniciar_sesion(
            request, form.cleaned_data['username'], form.cleaned_data['password'])
        if usuario:
            return redirect(_destino_seguro(request))
    elif request.method == 'POST':
        error = 'Ingrese su usuario y contraseña.'

    return render(request, 'cuentas/login.html', {
        'form': form, 'error': error,
        'next': request.GET.get('next', ''),
    }, status=200)


@require_POST
def logout_view(request):
    """Cierre de sesion solo por POST (con token CSRF), para que un enlace externo no cierre la sesion."""
    if request.user.is_authenticated:
        auditar(request, 'otro', request.user, evento='logout')
    logout(request)
    return redirect('cuentas:login')


def acceso_denegado(request, exception=None):
    """Pantalla «Acceso denegado» del prototipo. Tambien es el handler403 del proyecto."""
    return render(request, 'cuentas/acceso_denegado.html', status=403)


@never_cache
@login_required
def grilla(request):
    """Grilla PROVISORIA para probar el login y el aislamiento por corredora.

    El front-end la reemplaza por la grilla real (HDU 01). Lo importante es el origen
    de los datos: `calificaciones_visibles(request.user)`, nunca `Calificacion.objects.all()`.
    """
    registros = (calificaciones_visibles(request.user)
                 .select_related('corredora')
                 .order_by('-ejercicio', 'instrumento')[:100])
    return render(request, 'cuentas/grilla.html', {
        'registros': registros,
        'puede_ingresar': tiene_permiso(request.user, INGRESAR),
    })
