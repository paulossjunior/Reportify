from pydantic import BaseModel, field_validator, model_validator
from typing import List, Any , Callable, Optional
import os
from dotenv import load_dotenv
import airbyte as ab
from datetime import datetime
class AbstractDasboard(BaseModel):
    streams: List[str]
    repository: str = ""
    token: str = ""
    cache: Any = None
    save_func: Optional[Callable] = None
    report_dir: str = ""
    def model_post_init(self, __context):
        load_dotenv()
        self.repository = os.getenv("GITHUB_REPOSITORY", "")
        self.token = os.getenv("GITHUB_TOKEN", "")
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

