from pydantic import BaseModel, field_validator, model_validator
from typing import List, Any
import os
from dotenv import load_dotenv
import airbyte as ab

class AbstractDasboard(BaseModel):
    streams: List[str]
    repository: str = ""
    token: str = ""
    cache: Any = None

    def model_post_init(self, __context):
        load_dotenv()
        self.repository = os.getenv("REPOSITORY", "")
        self.token = os.getenv("TOKEN", "")
        self.fetch_data()

    def fetch_data(self):
        print(f"🔄 Buscando issues para {self.repository}...")
        try:
            source = ab.get_source(
                "source-github",
                install_if_missing=True,
                config={
                    "repositories": [self.repository],
                    "credentials": {"personal_access_token": self.token},
                },
            )
            source.check()
            source.select_streams(self.streams)
            cache = ab.get_default_cache()
            source.read(cache=cache)
            self.cache = cache
        except Exception as e:
            print(f"❌ Erro ao buscar: {str(e)}")
