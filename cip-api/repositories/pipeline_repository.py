"""
Pipeline Repository – storage for pipeline runs and app settings.

Backed by JSON files in cip-api/data/ (runs.json + settings.json).
Previously used MongoDB; the JSON backend has the same interface and is simpler to deploy
(no database server required on the EC2 instance).
"""

from repositories.json_file_repository import JsonFileRepository

# PipelineRepository is now an alias for the JSON file backend.
# Every caller (pipeline_service, pipeline_router, settings_router, llm_router, main)
# imports PipelineRepository – nothing else changes.
PipelineRepository = JsonFileRepository
