/* Ingreso de calificaciones en 3 pasos.
 *
 * Es solo una capa de presentación sobre el mismo formulario: los datos se siguen enviando de una vez
 * y el servidor valida y calcula todo igual que antes. Sin JavaScript, el formulario se ve completo en
 * una sola pantalla. Va en un archivo aparte porque la política CSP no permite scripts en línea.
 */
(function () {
  'use strict';

  var form = document.getElementById('form-ingreso');
  if (!form) { return; }

  var pasos = Array.prototype.slice.call(form.querySelectorAll('[data-paso]'));
  var indicadores = Array.prototype.slice.call(form.querySelectorAll('[data-ir-paso]'));
  var navegacion = document.getElementById('pasos-nav');
  var estado = document.getElementById('paso-estado');
  var resumen = document.getElementById('resumen-ingreso');
  var btnAnterior = form.querySelector('[data-accion="anterior"]');
  var btnSiguiente = form.querySelector('[data-accion="siguiente"]');
  var soloUltimo = Array.prototype.slice.call(form.querySelectorAll('[data-solo-paso]'));
  var TITULOS = ['Datos básicos', 'Montos', 'Factores y guardado'];
  var total = pasos.length;
  var actual = 1;

  function mostrar(elemento, visible) {
    elemento.classList.toggle('d-none', !visible);
  }

  /* Revisa los campos de un paso con las reglas HTML (required, min, max, step). El servidor vuelve a validar. */
  function validarPaso(numero) {
    var campos = pasos[numero - 1].querySelectorAll('input, select, textarea');
    var primero = null;
    Array.prototype.forEach.call(campos, function (campo) {
      var valido = campo.checkValidity();
      campo.classList.toggle('is-invalid', !valido);
      if (!valido && !primero) { primero = campo; }
    });
    if (primero) {
      primero.focus();
      primero.reportValidity();
      return false;
    }
    return true;
  }

  function valorDe(id) {
    var campo = document.getElementById(id);
    if (!campo) { return ''; }
    if (campo.tagName === 'SELECT') {
      return campo.selectedIndex >= 0 ? campo.options[campo.selectedIndex].text : '';
    }
    return campo.value;
  }

  function fechaLegible(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
    return m ? m[3] + '-' + m[2] + '-' + m[1] : iso;
  }

  function actualizarResumen() {
    if (!resumen) { return; }
    var montos = form.querySelectorAll('input[name^="monto_"]');
    var conValor = 0;
    Array.prototype.forEach.call(montos, function (campo) {
      var n = parseFloat(String(campo.value).replace(',', '.'));
      if (n > 0) { conValor += 1; }
    });
    var datos = {
      mercado: valorDe('id_mercado'),
      instrumento: valorDe('id_instrumento'),
      ejercicio: valorDe('id_ejercicio'),
      secuencia: valorDe('id_secuencia_evento'),
      fecha: fechaLegible(valorDe('id_fecha_pago')),
      montos: conValor + ' de ' + montos.length + ' columnas con monto'
    };
    Array.prototype.forEach.call(resumen.querySelectorAll('[data-resumen]'), function (dd) {
      dd.textContent = datos[dd.getAttribute('data-resumen')] || '—';
    });
  }

  function ir(numero, moverFoco) {
    actual = Math.min(Math.max(numero, 1), total);
    pasos.forEach(function (seccion, i) { mostrar(seccion, i + 1 === actual); });
    indicadores.forEach(function (boton) {
      var n = parseInt(boton.getAttribute('data-ir-paso'), 10);
      if (n === actual) { boton.setAttribute('aria-current', 'step'); } else { boton.removeAttribute('aria-current'); }
      boton.classList.toggle('paso-hecho', n < actual);
    });
    mostrar(btnAnterior, actual > 1);
    mostrar(btnSiguiente, actual < total);
    soloUltimo.forEach(function (boton) {
      mostrar(boton, actual === parseInt(boton.getAttribute('data-solo-paso'), 10));
    });
    if (resumen) { mostrar(resumen, actual === total); }
    if (actual === total) { actualizarResumen(); }
    estado.textContent = 'Paso ' + actual + ' de ' + total + ': ' + TITULOS[actual - 1];
    if (moverFoco) {
      var titulo = pasos[actual - 1].querySelector('h2');
      if (titulo) {
        titulo.focus();
        if (titulo.scrollIntoView) { titulo.scrollIntoView({ block: 'start' }); }
      }
    }
  }

  /* Avanza solo si los pasos intermedios están completos. Retroceder siempre se puede. */
  function irValidando(destino) {
    if (destino > actual) {
      for (var n = actual; n < destino; n += 1) {
        if (!validarPaso(n)) { ir(n, false); return; }
      }
    }
    ir(destino, true);
  }

  indicadores.forEach(function (boton) {
    boton.addEventListener('click', function () {
      irValidando(parseInt(boton.getAttribute('data-ir-paso'), 10));
    });
  });
  btnAnterior.addEventListener('click', function () { ir(actual - 1, true); });
  btnSiguiente.addEventListener('click', function () { irValidando(actual + 1); });

  /* Enter dentro de un campo avanza de paso en vez de enviar el formulario antes de tiempo. */
  form.addEventListener('keydown', function (evento) {
    if (evento.key === 'Enter' && actual < total && evento.target.tagName === 'INPUT') {
      evento.preventDefault();
      irValidando(actual + 1);
    }
  });

  mostrar(navegacion, true);
  Array.prototype.forEach.call(form.querySelectorAll('.solo-sin-pasos'), function (el) { mostrar(el, false); });
  ir(parseInt(form.getAttribute('data-paso-inicial'), 10) || 1, false);
}());