# RiesgoTI — Backend (`riesgoti-back`)

API REST de **RiesgoTI**, la plataforma de gestión de incidencias operativas y gobierno de riesgos de Seguridad de la Información alineada con ISO/IEC 27005, 27001 y 27002.

Este repositorio es el submódulo `back/` del superproyecto `riesgoti`. La guía completa de arranque (frontend incluido), los usuarios semilla y la solución de problemas están en el [README raíz](../README.md).

| Componente | Tecnología |
| --- | --- |
| API | Django 5.2, Django REST Framework, SimpleJWT, drf-spectacular (OpenAPI), django-filter, django-cors-headers |
| Base de datos | PostgreSQL 16 (`psycopg` 3); esquema fiel 1:1 a `docs/bd.sql` |
| Tareas asíncronas | Celery 5 con broker Redis 7 y resultados en `django-celery-results` |
| IA / RAG | PyMuPDF4LLM, LangChain Text Splitters, Sentence Transformers (embeddings locales), FAISS (CPU), Google Gen AI y OpenAI (LLM) con Pydantic para salidas estructuradas |
| Criptografía | `cryptography` (AES-256-GCM para las API keys de los proveedores de IA) |
| Pruebas | pytest + pytest-django |

---

## 1. Qué hace la API

Cada incidencia que registra un Reportante se guarda primero en una transacción y, al confirmarse (`transaction.on_commit()`), dispara dos tareas de IA independientes en `TAREA_IA`:

| Rama | Tarea Celery | Resultado |
| --- | --- | --- |
| Operativa (`ORIENTACION_OPERATIVA`) | `risks.run_operational_rag` | Pasos de resolución para el Reportante, con citas exactas a fragmentos de documentos autorizados (`CITA_ORIENTACION`). |
| Estratégica (`ANALISIS_INCIDENCIA`) | `risks.run_strategic_risk` | Vectores de riesgo (activo, amenaza, vulnerabilidad, consecuencia), agrupación por similitud con incidencias previas y propuesta de `VERSION_RIESGO` con citas a normativa interna. |

Si el proveedor de IA falla o ningún fragmento supera el umbral de similitud (`SIN_RESPALDO`), la incidencia sigue existiendo y pasa a `PENDIENTE_ATENCION_HUMANA`. Que el Reportante marque «Funcionó» cierra la incidencia, pero nunca detiene el análisis estratégico.

La base de conocimiento se alimenta con PDFs que sube el Administrador (`documents_rag.process_pdf_version`): se extraen página por página, se dividen por encabezados Markdown, se vectorizan con norma L2 y se indexan en FAISS (`IndexIDMap2(IndexFlatIP)`) con el `id` de `FRAGMENTO_DOCUMENTO`. Solo se consultan fragmentos de versiones `activa = True`, `procesamiento = 'AUTORIZADO'` y generadas con el modelo de embeddings vigente.

---

## 2. Requisitos

El backend está pensado para correr **en contenedores**; no necesitas Python en tu máquina.

- Docker Desktop 24+ con Docker Compose v2.
- El superproyecto clonado con submódulos (`git clone --recurse-submodules`), porque `docker-compose.yml` vive en la raíz y monta `./back`.
- Puertos libres: `5432` (PostgreSQL), `6379` (Redis), `5050` (pgAdmin) y `8000` (API).

---

## 3. Puesta en marcha

### 3.1 Variables de entorno

```bash
cp back/.env.example back/.env          # PowerShell: Copy-Item back/.env.example back/.env
```

| Variable | Descripción |
| --- | --- |
| `DEBUG`, `SECRET_KEY`, `ALLOWED_HOSTS` | Configuración de Django. Cambia `SECRET_KEY` fuera de desarrollo. |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | Conexión a PostgreSQL (`DB_HOST=db` dentro de Docker). |
| `DB_PORT_HOST`, `REDIS_PORT_HOST`, `PGADMIN_PORT` | Puertos publicados en tu máquina; cámbialos si chocan con otro servicio. |
| `PGADMIN_DEFAULT_EMAIL`, `PGADMIN_DEFAULT_PASSWORD` | Acceso a pgAdmin 4. |
| `RIESGOTI_MASTER_KEY` | **Obligatoria.** 32 bytes en Base64 para cifrar las API keys de IA. Sin ella el backend no arranca. |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Broker Redis y backend de resultados (`django-db`). |
| `CORS_ALLOWED_ORIGINS` | Orígenes del frontend (por defecto `http://localhost:5173`). |

Genera la clave maestra:

```bash
docker run --rm python:3.12-slim python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
```

> No cambies `RIESGOTI_MASTER_KEY` después de guardar API keys: las cifradas con la clave anterior dejarán de poder leerse.

### 3.2 Levantar servicios, migrar y sembrar

Desde la **raíz del superproyecto**:

```bash
docker compose up -d --build
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py seed_riesgoti
curl http://localhost:8000/api/v1/health/
```

El healthcheck debe responder `"status": "ok"`, `"database": "connected"` y `"master_key_loaded": true`.

La primera construcción instala PyTorch (CPU), PyMuPDF y FAISS, y el primer procesamiento de un PDF descarga el modelo `paraphrase-multilingual-mpnet-base-v2` al volumen `huggingface_cache`.

| Servicio | Contenedor | Dirección |
| --- | --- | --- |
| API (`runserver`, recarga al editar) | `backend` | http://localhost:8000/api/v1/ |
| Swagger UI / esquema OpenAPI | `backend` | http://localhost:8000/api/docs/ · http://localhost:8000/api/schema/ |
| Worker de IA (`celery -A config worker --pool=solo`) | `celery_worker` | — (no recarga: reinícialo tras cambiar tareas) |
| PostgreSQL 16 | `db` | `localhost:5432` |
| Redis 7 | `redis` | `localhost:6379` |
| pgAdmin 4 (servidor preconfigurado en `docker/pgadmin/servers.json`) | `pgadmin` | http://localhost:5050 |

### 3.3 Stack aislado para las pruebas E2E

`docker-compose.e2e.yml` (raíz) define un stack desechable, proyecto `riesgoti-e2e`, para la suite Playwright de `front/e2e/`, que lo levanta y destruye sola (`pnpm test:e2e`, ver `front/README.md`):

- **Base de datos en `tmpfs`:** cada arranque ejecuta `migrate` y `seed_riesgoti` sobre una BD vacía.
- **`storage/` en un volumen propio:** PDF, evidencias e índices FAISS no se mezclan con los de desarrollo.
- **API en el puerto 8001**, con CORS para el front de pruebas (5174) y `LOGIN_THROTTLE_RATE=1000/min`.
- **Reutiliza recursos existentes:** la imagen `riesgo_ti-backend` y el volumen `riesgo_ti_huggingface_cache`.
- **Modelo de embeddings precargado:** `RIESGOTI_PRELOAD_EMBEDDING_MODEL` (solo en el servicio `backend` de este stack) hace que `runserver` cargue el modelo `sentence-transformers` antes de abrir el puerto (≈ 40 s), de modo que el healthcheck lo da por sano ya caliente y la primera prueba de conectividad IA responde en menos de un segundo. Lo implementa `preload_embedding_model` (`apps/ai_config/services.py`), invocado desde `AiConfigConfig.ready()`; no actúa en `migrate`, `seed_riesgoti`, `pytest` ni en el proceso vigilante del autoreload, y un fallo de carga no impide arrancar. Su valor debe coincidir con `modelo_embedding` de la configuración semilla.

Puede convivir con el stack de desarrollo. Manualmente:

```bash
docker compose -f docker-compose.e2e.yml up -d --wait   # sano cuando terminó la semilla y el modelo está cargado
docker compose -f docker-compose.e2e.yml down -v
```

---

## 4. Estructura

```text
back/
├── config/               # settings, urls (/api/v1/), celery, healthcheck
├── apps/
│   ├── accounts/         # USUARIO, ROL, PERMISO; login JWT, RBAC; comando seed_riesgoti
│   ├── ai_config/        # CONFIGURACION_IA_RAG; cifrado AES-256-GCM (crypto.py); prueba de conexión
│   ├── assets_matrix/    # Activos, tipos de activo y matriz de riesgo 5×5 versionada
│   ├── documents_rag/    # Versiones de documentos, chunking, embeddings, índice FAISS y tareas de ingesta
│   ├── incidents/        # INCIDENCIA, evidencias, orientación operativa, atención humana
│   ├── risks/            # VERSION_RIESGO, evaluación, decisiones, dashboard; cliente LLM; requeue_ai_tasks
│   └── audit/            # EVENTO_AUDITORIA y AuditLogMixin
├── docker/pgadmin/       # servers.json de pgAdmin
├── storage/              # pdfs/, evidences/, faiss_indices/ (no se versiona su contenido)
├── conftest.py           # BD e índice FAISS aislados para pytest
├── Dockerfile            # python:3.12-slim + PyTorch CPU + requirements.txt
└── requirements.txt
```

Cada app sigue la misma división: `models.py` (tablas de `bd.sql`), `serializers.py` (DTOs de entrada y salida), `services.py` (lógica de negocio), `views.py` (ViewSets/APIViews delgados), `urls.py`, `tasks.py` (Celery) y `tests/`.

---

## 5. Endpoints

Todos cuelgan de `/api/v1/` y, salvo login, refresh y health, exigen `Authorization: Bearer <access>`. El detalle de cada payload está en Swagger (`/api/docs/`).

| Área | Endpoints |
| --- | --- |
| Sistema | `GET health/` |
| Autenticación | `POST auth/login/`, `POST auth/refresh/`, `GET auth/me/` |
| Usuarios y roles | `admin/users/` (listar, ver, crear, editar parcial), `admin/roles/` (listar, ver, crear, actualizar), `GET admin/permissions/` |
| Configuración IA/RAG | `GET/PUT admin/ai-config/`, `POST admin/ai-config/test-connection/` |
| Activos y matriz | `assets/` (listar, ver, crear, editar parcial), `GET asset-types/`, `GET matrices/active/`, `POST admin/matrices/publish/` |
| Base de conocimiento | `admin/document-versions/` (listar, ver), `POST …/upload/`, `GET …/{id}/preview/`, `POST …/{id}/authorize/`, `…/activate/`, `…/deactivate/`, `…/retry/`, `…/reindex/` |
| Incidencias | `incidents/` (listar, ver, crear), `GET …/{id}/operational-guidance/`, `POST …/{id}/orientation-feedback/`, `POST …/{id}/start-attention/`, `PATCH …/{id}/attention/`, `POST …/{id}/retry-strategic/`, `GET …/{id}/evidences/{evidencia_id}/download/` |
| Riesgos | `risk-versions/` (listar, ver), `PATCH …/{id}/incidents/{analisis_id}/remove/` y `…/restore/`, `POST …/{id}/confirm-grouping/`, `POST …/{id}/evaluate/`, `POST …/{id}/decision/`, `GET risks/dashboard/` |
| Auditoría | `GET admin/audit-events/` |

El token de acceso dura 30 minutos y el de refresco 1 día. Los claims incluyen `usuario_id`, `nombre_completo`, `rol_codigo` y `permisos`, que el frontend usa para elegir el portal por rol.

---

## 6. Comandos de gestión

| Comando | Para qué |
| --- | --- |
| `python manage.py seed_riesgoti` | Carga roles, permisos, 6 usuarios de prueba, activos, matriz 5×5, configuración IA/RAG, documentos, incidencias y riesgos de demostración. Idempotente: no duplica ni reactiva versiones ya publicadas. |
| `python manage.py requeue_ai_tasks` | Vuelve a encolar las tareas de IA pendientes (útil si el worker estuvo caído). |
| `python manage.py requeue_ai_tasks --dry-run` | Solo lista las tareas que se re-encolarían. |
| `python manage.py requeue_ai_tasks --stale-minutes 10` | Libera tareas atascadas en `PROCESANDO` hace más de N minutos. |

Ejecútalos con `docker compose exec backend …` desde la raíz del superproyecto.

---

## 7. Pruebas

```bash
docker compose exec backend pytest
docker compose exec backend pytest apps/risks -q      # una sola app
```

Cada sesión crea su propia base de datos y un índice FAISS aislado desde cero (`conftest.py`), así que no tocan los datos de desarrollo.

| Suite | Cubre |
| --- | --- |
| `accounts/tests/test_auth_rbac.py`, `test_seed.py` | Login JWT, permisos RBAC e idempotencia de la semilla |
| `ai_config/tests/test_ai_config.py` | Versionado de la configuración IA/RAG, cifrado y máscaras de API keys |
| `assets_matrix/tests/test_assets_matrix.py` | Activos y publicación de matrices sin alterar evaluaciones históricas |
| `documents_rag/tests/test_documents_rag.py` | Ingesta de PDF, chunking, FAISS y filtros del retriever |
| `incidents/tests/test_incidents.py` | Registro transaccional, historial de estados, orientación y atención humana |
| `risks/tests/test_celery_workers.py`, `test_risk_decisions_and_sod.py` | Ramas de `TAREA_IA`, evaluación 5×5, decisiones y segregación de funciones |

---

## 8. Convenciones obligatorias

Antes de contribuir revisa `CLAUDE.md` y `agents/rules/clean_code_and_architecture.md` en el superproyecto. Lo esencial:

- **Fidelidad a `docs/bd.sql`.** Cada modelo declara `Meta.db_table` y `db_column` exactos. No se renombran tablas ni columnas. La única tabla técnica añadida es `CONFIGURACION_IA_RAG`. Las PK compuestas usan `CompositePrimaryKey` o `UniqueConstraint`, y `ultima_modificacion` usa `auto_now=True` más un trigger en la migración.
- **DTOs explícitos.** Nunca se devuelven entidades crudas: cada endpoint usa un `*InputSerializer` para validar y un `*OutputSerializer` para responder.
- **Lógica en servicios.** Las vistas validan, delegan en `services.py` y serializan la salida.
- **Secretos cifrados.** `api_key_llm` y `api_key_embedding` se guardan como `Base64(IV_12B || AuthTag_16B || Ciphertext)` y solo se exponen sus máscaras.
- **Auditoría.** Toda mutación crítica registra un `EVENTO_AUDITORIA` mediante `AuditLogMixin`.
- **Segregación de funciones (ISO/IEC 27001).** El rol `ADMIN` recibe `403 Forbidden` en evaluación y decisión de riesgos; solo `ANALISTA` evalúa y emite `VALIDADA`, `CORREGIDA` o `RECHAZADA`.
- **Sin autoentrenamiento.** Las notas de los analistas nunca se indexan en FAISS; el conocimiento entra solo como una nueva `VERSION_DOCUMENTO` autorizada por el Administrador.
- **Inmutabilidad histórica.** Desactivar un documento o publicar una nueva matriz no altera las citas ni las evaluaciones ya registradas.

---

## 9. Control de versiones

Este repositorio es un submódulo: haz commit aquí primero y luego actualiza la referencia en el superproyecto (`git add back`). No se versionan `.env`, el contenido de `storage/`, `roadmap/` ni `desktop.ini`. Los `.gitattributes` fijan el fin de línea en LF porque el código se monta en contenedores Linux.
