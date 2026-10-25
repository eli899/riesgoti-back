import os
import sys

from django.apps import AppConfig


class AiConfigConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.ai_config'
    label = 'ai_config'
    verbose_name = 'Configuración IA/RAG'

    def ready(self):
        from apps.ai_config.services import preload_embedding_model

        preload_embedding_model(sys.argv, os.environ)
