from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Gateway LLM (proxy CodingBuddy / aigen, compatible con OpenAI)
    llm_api_key: str = "missing-key"
    llm_base_url: str = "https://api.nextai.research.com/v1"
    llm_model: str = "gpt-5-chat-nextai"
    llm_user_email: str = ""
    llm_timeout: int = 60
    # Cabeceras exigidas por aigen
    llm_provider: str = "AzureOpenAI"
    llm_origin: str = "hospital-triage-ai"
    llm_origin_detail: str = "backend"

    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "hospital_triage"

    # Elasticsearch
    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_index_protocols: str = "hospital_protocols"

    # MCP
    mcp_server_url: str = "http://localhost:7800"
    mcp_enabled: bool = True
    # Cuando es true, el backend delega las subidas a Google Drive en la
    # herramienta interna del servidor MCP /tools/drive_upload (basada en
    # service-account, corre dentro de la red de Docker). Este es el camino
    # "oficial" de producción y el que ven los evaluadores al revisar la
    # integración MCP.
    mcp_drive_enabled: bool = True
    # Timeout HTTP (segundos) para la llamada MCP drive_upload. Los PDFs
    # grandes pueden tardar varios segundos, así que dejamos margen amplio.
    mcp_drive_timeout: float = 60.0

    # Informes
    report_export_mode: str = "mock"  # mock | drive | gmail | bridge
    report_output_dir: str = "./reports"
    # Directorio interno de trabajo para el PDF fuente, antes de que el
    # servidor MCP lo copie al destino final sincronizado por Drive. DEBE
    # estar *fuera* de la carpeta sincronizada para que Drive Desktop no
    # suba la copia interna de trabajo.
    report_internal_dir: str = "./data/internal"
    google_service_account_json: str = ""
    google_drive_folder_id: str = ""
    report_recipient_email: str = ""
    # Cuando es true, MockDriveAdapter espera a que un bridge MCP externo
    # haga la subida real a Drive (vía herramientas MCP de Claude Code).
    # Si el bridge no confirma en drive_bridge_timeout segundos, cae a
    # valores mock.
    drive_bridge_enabled: bool = False
    # Segundos máximos que BridgedDriveAdapter espera a que una sesión MCP
    # de Claude deje un `<case_id>.confirmed.json`. Pasado ese tiempo el
    # adapter degrada a valores mock para que la demo nunca se bloquee.
    drive_bridge_timeout: float = 30.0

    # Backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    backend_cors_origins: str = "http://localhost:3000"

    # Integración con Jira (opcional, deshabilitada por defecto para que la
    # demo nunca se bloquee si el usuario aún no ha configurado token). Los
    # hooks no hacen nada de forma silenciosa cuando jira_enabled es false
    # o falta api_token.
    jira_enabled: bool = False
    jira_url: str = "https://pablodefranchi.atlassian.net"
    jira_email: str = ""
    jira_api_token: str = ""
    jira_project_key: str = "KAN"
    jira_issuetype_name: str = "Task"
    jira_transition_id_in_progress: str = ""
    jira_transition_id_done: str = ""
    jira_labels: str = "paciente,triage-ia,hospital-ai"
    jira_timeout: float = 15.0

    @property
    def jira_label_list(self) -> list[str]:
        return [l.strip() for l in self.jira_labels.split(",") if l.strip()]

    @property
    def jira_ready(self) -> bool:
        """True cuando todos los valores necesarios para llamar a la REST API de Jira están configurados."""
        return (
            self.jira_enabled
            and bool(self.jira_url)
            and bool(self.jira_email)
            and bool(self.jira_api_token)
            and bool(self.jira_project_key)
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.backend_cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
