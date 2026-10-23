from decimal import Decimal
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.accounts.models import Usuario
from apps.ai_config.crypto import EnvelopeCryptoService
from apps.ai_config.models import ConfiguracionIARAG
from apps.assets_matrix.models import Activo
from apps.incidents.services import IncidentService
from apps.risks.llm_client import DETERMINISTIC_PROVIDER, LLMClient
from apps.risks.llm_schemas import OperationalGuidanceLLMOutput, OperationalStepOutput
from apps.risks.models import (
    AnalisisIncidencia,
    CitaOrientacion,
    CitaVersionRiesgo,
    DecisionRiesgo,
    OrientacionOperativa,
    Riesgo,
    TareaIA,
    VersionIncidencia,
)
from apps.risks.tasks import run_operational_rag_task, run_strategic_risk_task
from conftest import ANALISTA_EMAIL, REPORTANTE_EMAIL

pytestmark = pytest.mark.django_db

ERP_TITLE = 'ERP lento con degradaciones de rendimiento'
ERP_TEXT = ('Los servicios críticos del ERP presentan degradaciones de rendimiento; se requiere monitoreo de capacidad '
            'y umbrales de alerta.')


@pytest.fixture
def reportante():
    return Usuario.objects.get(correo=REPORTANTE_EMAIL)


@pytest.fixture
def sin_riesgos_semilla():
    """Aísla las pruebas de agrupación de los riesgos semilla RSG-0001..0005 (se revierte al terminar la prueba)."""
    Riesgo.objects.all().delete()


@pytest.fixture
def relaxed_rag():
    """Umbral RAG acorde a los embeddings deterministas de las pruebas (FakeSentenceTransformer)."""
    ConfiguracionIARAG.objects.filter(activa=True).update(umbral_similitud=Decimal('0.300'))


def _incident(reportante, titulo=ERP_TITLE, descripcion=ERP_TEXT, codigo_activo='ACT-001'):
    incidencia, tarea_op, tarea_est = IncidentService.create_incident_transactional(
        reportante=reportante, titulo=titulo, descripcion=descripcion,
        activo_reportado=Activo.objects.get(codigo=codigo_activo),
    )
    return incidencia, tarea_op, tarea_est


def _status(incidencia) -> str:
    return IncidentService.get_current_status(type(incidencia).objects.get(pk=incidencia.pk))


# ---------------------------------------------------------------------------
# Rama Operativa
# ---------------------------------------------------------------------------
def test_sugerencia_con_citas_autorizadas_en_modo_determinista(reportante, relaxed_rag):
    incidencia, tarea_op, _ = _incident(reportante)

    result = run_operational_rag_task(tarea_op.id)

    assert result['status'] == 'ok' and result['tipo'] == 'SUGERENCIA'
    orientacion = OrientacionOperativa.objects.get(tarea=tarea_op)
    citas = list(CitaOrientacion.objects.filter(orientacion=orientacion).select_related('fragmento__version_documento'))
    assert citas and orientacion.pasos.count() == len(citas)
    for cita in citas:  # DoD: ninguna cita apunta a un fragmento no autorizado, inactivo o no operativo.
        version = cita.fragmento.version_documento
        assert version.activa and version.procesamiento == 'AUTORIZADO' and version.finalidad in ('OPERATIVA', 'AMBAS')
        assert f'[{cita.numero}]' in orientacion.pasos.get(orden=cita.numero).instruccion
    tarea_op.refresh_from_db()
    assert tarea_op.estado == 'COMPLETADA' and tarea_op.proveedor == DETERMINISTIC_PROVIDER and tarea_op.terminada_en
    assert _status(incidencia) == 'EN_ANALISIS'  # Espera la confirmación del reportante.


def test_sin_respaldo_no_invoca_llm_y_deriva_a_n2(reportante):
    ConfiguracionIARAG.objects.filter(activa=True).update(umbral_similitud=Decimal('0.999'))
    incidencia, tarea_op, _ = _incident(reportante)

    with mock.patch.object(LLMClient, 'generate') as generate:
        result = run_operational_rag_task(tarea_op.id)

    generate.assert_not_called()
    assert result['tipo'] == 'SIN_RESPALDO' and result['escalada'] is True
    assert OrientacionOperativa.objects.get(tarea=tarea_op).citas.count() == 0
    assert _status(incidencia) == 'PENDIENTE_ATENCION_HUMANA'


def test_reporte_sensible_se_deriva_sin_consultar_documentos(reportante):
    incidencia, tarea_op, _ = _incident(
        reportante, titulo='Correo de phishing', descripcion='Recibí un correo que pide mi contraseña en un enlace externo.',
        codigo_activo='ACT-002',
    )
    with mock.patch('apps.risks.services.FaissVectorStore.search_authorized_fragments') as search:
        result = run_operational_rag_task(tarea_op.id)

    search.assert_not_called()
    orientacion = OrientacionOperativa.objects.get(tarea=tarea_op)
    assert result['tipo'] == 'SENSIBLE' and orientacion.pasos.count() == 0 and 'contraseña' in orientacion.advertencia
    assert _status(incidencia) == 'PENDIENTE_ATENCION_HUMANA'


def test_fallo_del_proveedor_marca_error_y_deriva_inv01(reportante, relaxed_rag):
    incidencia, tarea_op, _ = _incident(reportante)
    with mock.patch('apps.risks.services.FaissVectorStore.search_authorized_fragments', side_effect=TimeoutError('proveedor caído')):
        result = run_operational_rag_task(tarea_op.id)

    tarea_op.refresh_from_db()
    assert result['status'] == 'error'
    assert tarea_op.estado == 'ERROR' and tarea_op.error_codigo == 'TimeoutError' and 'proveedor caído' in tarea_op.error_detalle
    assert _status(incidencia) == 'PENDIENTE_ATENCION_HUMANA'


def test_worker_operativo_es_idempotente(reportante, relaxed_rag):
    _, tarea_op, _ = _incident(reportante)
    assert run_operational_rag_task(tarea_op.id)['status'] == 'ok'
    assert run_operational_rag_task(tarea_op.id)['status'] == 'skipped'
    assert OrientacionOperativa.objects.filter(tarea=tarea_op).count() == 1


def test_no_pisa_una_incidencia_ya_tomada_por_un_analista(reportante):
    ConfiguracionIARAG.objects.filter(activa=True).update(umbral_similitud=Decimal('0.999'))
    incidencia, tarea_op, _ = _incident(reportante)
    IncidentService.start_attention(incidencia=incidencia, analista=Usuario.objects.get(correo=ANALISTA_EMAIL))

    result = run_operational_rag_task(tarea_op.id)

    assert result['tipo'] == 'SIN_RESPALDO' and result['escalada'] is False
    assert _status(incidencia) == 'EN_ATENCION'


def _llm_enabled():
    return mock.patch.object(LLMClient, 'is_deterministic', new_callable=mock.PropertyMock, return_value=False)


def test_citas_inventadas_por_el_llm_se_descartan(reportante, relaxed_rag):
    _, tarea_op, _ = _incident(reportante)
    salida = OperationalGuidanceLLMOutput(
        tipo='SUGERENCIA', resumen='El ERP presenta degradación de rendimiento.',
        pasos=[OperationalStepOutput(orden=1, instruccion='Reporta la lentitud al monitoreo de capacidad [1] [7].')],
        numeros_citas_usadas=[1, 7, 99],
    )
    with _llm_enabled(), mock.patch.object(LLMClient, '_gemini', return_value=salida):
        run_operational_rag_task(tarea_op.id)

    orientacion = OrientacionOperativa.objects.get(tarea=tarea_op)
    assert list(orientacion.citas.values_list('numero', flat=True)) == [1]
    assert orientacion.pasos.get().instruccion == 'Reporta la lentitud al monitoreo de capacidad [1].'
    tarea_op.refresh_from_db()
    assert tarea_op.proveedor == 'GEMINI'


def test_sugerencia_del_llm_sin_citas_validas_se_trata_como_sin_respaldo(reportante, relaxed_rag):
    incidencia, tarea_op, _ = _incident(reportante)
    salida = OperationalGuidanceLLMOutput(
        tipo='SUGERENCIA', resumen='Reinicia el equipo y prueba de nuevo.',
        pasos=[OperationalStepOutput(orden=1, instruccion='Reinicia el equipo [9].')], numeros_citas_usadas=[9],
    )
    with _llm_enabled(), mock.patch.object(LLMClient, '_gemini', return_value=salida):
        result = run_operational_rag_task(tarea_op.id)

    assert result['tipo'] == 'SIN_RESPALDO'
    assert _status(incidencia) == 'PENDIENTE_ATENCION_HUMANA'


# ---------------------------------------------------------------------------
# Rama Estratégica
# ---------------------------------------------------------------------------
def test_nuevo_riesgo_candidato_con_vectores_iso_27005(reportante, relaxed_rag, sin_riesgos_semilla):
    incidencia, _, tarea_est = _incident(reportante)

    result = run_strategic_risk_task(tarea_est.id)

    assert result['status'] == 'ok' and result['caso'] == 'NUEVO_RIESGO'
    analisis = AnalisisIncidencia.objects.get(tarea=tarea_est)
    assert analisis.activo_identificado == 'ERP Contable'
    assert analisis.amenaza == 'Interrupción o degradación del servicio'
    assert analisis.vulnerabilidad == 'NO_DETERMINADO'
    vinculo = VersionIncidencia.objects.get(analisis=analisis)
    version = vinculo.version
    assert version.riesgo.codigo == f'RSG-{version.riesgo_id:04d}' and version.numero == 1 and version.origen == 'IA'
    assert vinculo.estado == 'SUGERIDA' and vinculo.similitud == Decimal('1.0000') and vinculo.motivo_similitud == 'Incidencia de origen.'
    for cita in CitaVersionRiesgo.objects.filter(version=version).select_related('fragmento__version_documento'):
        dv = cita.fragmento.version_documento
        assert dv.activa and dv.procesamiento == 'AUTORIZADO' and dv.finalidad in ('ESTRATEGICA', 'AMBAS')
    assert version.origen_recomendacion == ('NORMATIVA_INTERNA' if version.citas.exists() else None)


def test_cierre_operativo_funciono_no_detiene_la_rama_estrategica_inv02(reportante, relaxed_rag):
    incidencia, tarea_op, tarea_est = _incident(reportante)
    run_operational_rag_task(tarea_op.id)
    IncidentService.register_orientation_feedback(incidencia=incidencia, actor=reportante, resultado='FUNCIONO')
    assert _status(incidencia) == 'CERRADA'

    result = run_strategic_risk_task(tarea_est.id)

    assert result['status'] == 'ok'
    tarea_est.refresh_from_db()
    assert tarea_est.estado == 'COMPLETADA' and AnalisisIncidencia.objects.filter(tarea=tarea_est).exists()


@override_settings(RISK_GROUPING_THRESHOLD=0.5)
def test_incidencias_similares_se_agrupan_en_la_version_pendiente(reportante, relaxed_rag, sin_riesgos_semilla):
    _, _, primera = _incident(reportante)
    _, _, segunda = _incident(reportante, titulo='ERP lento al guardar', descripcion='El ERP presenta degradaciones de rendimiento al guardar asientos.')

    r1 = run_strategic_risk_task(primera.id)
    r2 = run_strategic_risk_task(segunda.id)

    assert r2['caso'] == 'AGRUPACION' and r2['riesgo'] == r1['riesgo'] and r2['version'] == 1
    vinculo = VersionIncidencia.objects.get(analisis__tarea=segunda)
    assert vinculo.estado == 'SUGERIDA' and Decimal('0.5') <= vinculo.similitud < Decimal('1')
    assert 'Similitud semántica' in vinculo.motivo_similitud


@override_settings(RISK_GROUPING_THRESHOLD=0.5)
def test_recurrencia_sobre_riesgo_validado_crea_nueva_version(reportante, relaxed_rag, sin_riesgos_semilla):
    _, _, primera = _incident(reportante)
    r1 = run_strategic_risk_task(primera.id)
    version_1 = Riesgo.objects.get(codigo=r1['riesgo']).versiones.get(numero=1)
    DecisionRiesgo.objects.create(version=version_1, accion='VALIDADA', analista=Usuario.objects.get(correo=ANALISTA_EMAIL))
    _, _, tercera = _incident(reportante, titulo='ERP lento otra vez', descripcion='Nuevamente el ERP presenta degradaciones de rendimiento.')

    r3 = run_strategic_risk_task(tercera.id)

    assert r3['caso'] == 'RECURRENCIA_NUEVA_VERSION' and r3['riesgo'] == r1['riesgo'] and r3['version'] == 2
    assert version_1.incidencias_vinculadas.count() == 1  # El vínculo histórico de v1 queda intacto.


@override_settings(RISK_GROUPING_THRESHOLD=0.99)
def test_incidencias_distintas_generan_riesgos_distintos(reportante, relaxed_rag, sin_riesgos_semilla):
    _, _, erp = _incident(reportante)
    _, _, impresora = _incident(reportante, titulo='Impresora imprime hojas en blanco',
                                descripcion='La impresora del piso 3 saca hojas en blanco al imprimir.', codigo_activo='ACT-004')
    assert run_strategic_risk_task(erp.id)['riesgo'] != run_strategic_risk_task(impresora.id)['riesgo']


def test_fallo_estrategico_no_altera_el_estado_operativo_y_se_reintenta(reportante, analista_client, django_capture_on_commit_callbacks):
    incidencia, _, tarea_est = _incident(reportante)
    with mock.patch('apps.risks.services.FaissVectorStore.search_authorized_fragments', side_effect=RuntimeError('cuota agotada')):
        assert run_strategic_risk_task(tarea_est.id)['status'] == 'error'
    tarea_est.refresh_from_db()
    assert tarea_est.estado == 'ERROR' and _status(incidencia) == 'EN_ANALISIS'

    with mock.patch('apps.risks.services.dispatch_ai_tasks') as dispatch, django_capture_on_commit_callbacks(execute=True):
        response = analista_client.post(f'/api/v1/incidents/{incidencia.id}/retry-strategic/')

    assert response.status_code == 202
    body = response.json()
    assert body['tarea_ia']['intento'] == 2 and body['tarea_ia']['estado'] == 'PENDIENTE'
    assert body['tarea_ia']['clave_idempotencia'] == f'inc-{incidencia.id}-est-v2'
    dispatch.assert_called_once_with(body['tarea_ia']['id'])
    assert run_strategic_risk_task(body['tarea_ia']['id'])['status'] == 'ok'
    detalle = analista_client.get(f'/api/v1/incidents/{incidencia.id}/').json()
    assert detalle['tareas_ia']['estrategica']['intento'] == 2 and detalle['riesgos_vinculados']


def test_retry_solo_aplica_a_tareas_en_error(reportante, analista_client, reportante_client):
    incidencia, _, _ = _incident(reportante)
    assert analista_client.post(f'/api/v1/incidents/{incidencia.id}/retry-strategic/').status_code == 400
    assert reportante_client.post(f'/api/v1/incidents/{incidencia.id}/retry-strategic/').status_code == 403


# ---------------------------------------------------------------------------
# Cliente LLM y re-encolado
# ---------------------------------------------------------------------------
def test_llm_client_modo_determinista_segun_configuracion():
    cfg = ConfiguracionIARAG.objects.get(activa=True)
    assert LLMClient(cfg).is_deterministic and LLMClient(cfg).provider_label == DETERMINISTIC_PROVIDER

    cfg.api_key_llm_cifrada, _ = EnvelopeCryptoService.encrypt_api_key('AIzaSyClavePrueba1234')
    assert not LLMClient(cfg).is_deterministic and LLMClient(cfg).provider_label == 'GEMINI'

    cfg.proveedor_llm, cfg.endpoint_base_llm = 'HUGGINGFACE_LOCAL', None
    assert LLMClient(cfg).is_deterministic
    cfg.endpoint_base_llm = 'http://ollama:11434/v1'
    assert not LLMClient(cfg).is_deterministic


def test_requeue_ai_tasks_reencola_pendientes_y_recupera_abandonadas(reportante):
    _, tarea_op, tarea_est = _incident(reportante)
    TareaIA.objects.filter(pk=tarea_est.pk).update(estado='PROCESANDO', iniciada_en=None)

    with mock.patch('apps.risks.management.commands.requeue_ai_tasks.dispatch_ai_tasks') as dispatch:
        call_command('requeue_ai_tasks', '--stale-minutes', '30', stdout=StringIO())

    reencoladas = dispatch.call_args.args
    assert tarea_op.id in reencoladas and tarea_est.id in reencoladas
    assert TareaIA.objects.get(pk=tarea_est.pk).estado == 'PENDIENTE'


def test_first_sentence_omite_prefijo_y_encabezados_numerados():
    from apps.risks.services import first_sentence

    contenido = ('[Documento: PRO-ACC-01 v1.4 | Sección: Procedimiento > 7. Acceso remoto]\n## 7. Acceso remoto\n\n'
                 'El acceso remoto a la red corporativa requiere autenticación multifactor. Segunda oración.')
    assert first_sentence(contenido) == 'El acceso remoto a la red corporativa requiere autenticación multifactor.'


def test_regla_determinista_de_acceso_remoto(reportante):
    from apps.risks.services import StrategicRiskAnalysisService

    incidencia, _, _ = _incident(reportante, titulo='No puedo conectarme a la VPN',
                                 descripcion='La VPN rechaza la conexión remota desde casa.', codigo_activo='ACT-003')
    salida = StrategicRiskAnalysisService.deterministic_extraction(incidencia, [])
    assert salida.amenaza == 'Indisponibilidad del acceso remoto' and salida.activo_identificado == 'VPN corporativa'
