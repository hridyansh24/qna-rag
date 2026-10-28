from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "development"

    DATABASE_URL: str = "mysql+asyncmy://app_user:password@mysql:3306/qna"
    REDIS_URL: str = "redis://redis:6379/0"

    JWT_PRIVATE_KEY: str = ""
    JWT_PUBLIC_KEY: str = ""

    # Required for /auth/oauth2-callback to accept X-Auth-Request-* identity
    # headers. Unset (the default) means the callback refuses every request —
    # fail closed, since those headers are otherwise a trivial impersonation
    # vector for anyone with network access to this service. Set this to a
    # random secret and configure the same value in the OAuth2 reverse proxy
    # sitting in front of this service, which must strip any client-supplied
    # copy of this header and set its own.
    OAUTH2_PROXY_SHARED_SECRET: str = ""

    CORS_ORIGINS: str = (
        "http://localhost:8080,http://localhost:8000,http://localhost:5173"
    )
    FRONTEND_URL: str = "http://localhost:8080"

    # Bootstrap — set once to create the first admin; ignored once an admin exists
    ADMIN_USERNAME: str = ""
    ADMIN_PASSWORD: str = ""

    # --- RAG services (docs/design-rag.md §9.3) ---
    OLLAMA_URL: str = "http://ollama:11434"
    INFINITY_URL: str = "http://infinity:7997"
    CHROMA_URL: str = "http://chromadb:8000"
    RESOURCE_DIR: str = "/data/resources"

    # Embedding models a profile may use. Infinity must serve each one
    # (INFINITY_MODEL_ID in .env lists what it actually loads).
    RAG_EMBEDDING_MODELS: str = (
        "sentence-transformers/all-MiniLM-L6-v2,Alibaba-NLP/gte-Qwen2-1.5B-instruct"
    )
    # Chunk sizes are counted with this tokenizer for every profile (§7.2).
    # Its tokenizer.json is vendored in services/rag/assets/, so nothing is
    # downloaded at runtime; this names which model the file came from.
    CHUNK_TOKENIZER: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Ingestion embeds in batches of this many chunks per model (§7.5):
    # "model=n,…". A model not listed uses 32.
    RAG_EMBED_BATCH_SIZES: str = (
        "sentence-transformers/all-MiniLM-L6-v2=32,"
        "Alibaba-NLP/gte-Qwen2-1.5B-instruct=4"
    )
    # An ingestion batch through gte-Qwen2 on CPU can take minutes (§7.5). A
    # query embedding is normally quick, but gte-Qwen2's first one after an
    # idle period took over 30 s on the VM (2026-10-27), and a 503 there ends
    # a harness run. 120 s still fits inside COMPARE_BUDGET_S.
    INFINITY_QUERY_TIMEOUT_S: float = 120.0
    INFINITY_BATCH_TIMEOUT_S: float = 300.0

    RAG_DEFAULT_PROFILE: str = "sliding-window"
    # Calibrated by the §11.3 method on the eval course (docs/design-rag.md).
    RAG_DEFAULT_THRESHOLD: float = 0.35
    RAG_DEFAULT_MODEL: str = "qwen2.5:1.5b"

    # Generation bounds (§8.1). num_predict caps an answer's length; each
    # auto-answer attempt gives up after OLLAMA_TIMEOUT_S. A /rag/compare
    # call has COMPARE_BUDGET_S from arrival, under the harness's 180 s, and
    # auto-answers wait COMPARE_GRACE_S after the last compare call ends.
    OLLAMA_NUM_PREDICT: int = 512
    OLLAMA_TIMEOUT_S: float = 150.0
    COMPARE_BUDGET_S: float = 165.0
    COMPARE_GRACE_S: float = 5.0

    # Runtime secret for shallow-cloning course repositories. Set only in the
    # .env on each machine; never committed, never a CI/CD variable (T4).
    GITLAB_TOKEN: str = ""
    # The token is only ever sent to these hosts (§9.4).
    RAG_GIT_HOSTS: str = "git.doit.wisc.edu"
    # Bounds how much a huge repository can download before the caps apply (§7.1).
    RAG_CLONE_TIMEOUT_S: float = 120.0

    @property
    def rag_embedding_models_list(self) -> list[str]:
        return [m.strip() for m in self.RAG_EMBEDDING_MODELS.split(",") if m.strip()]

    @property
    def rag_embed_batch_sizes(self) -> dict[str, int]:
        sizes = {}
        for item in self.RAG_EMBED_BATCH_SIZES.split(","):
            model, sep, n = item.strip().rpartition("=")
            if sep and model:
                sizes[model.strip()] = int(n)
        return sizes

    @property
    def rag_git_hosts_list(self) -> list[str]:
        return [h.strip().lower() for h in self.RAG_GIT_HOSTS.split(",") if h.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"


settings = Settings()
